#!/usr/bin/env python3
"""Reusable Playwright web-crawl harness for the injector.world QA audit.

Collects evidence (screenshots, load timing, console errors, broken images,
bot-protection signals) across desktop and mobile emulation, and records
findings + a crawl manifest as append-only JSON.

Usage:
    python scripts/harness.py desktop           # crawl seed list on 1920x1080
    python scripts/harness.py iphone-13         # iPhone 13 emulation
    python scripts/harness.py pixel-7           # Pixel 7 emulation
    python scripts/harness.py desktop URL [URL...]   # explicit URL list

Options:
    --headed         run with a visible browser window
    --slowmo MS      pause between actions in ms (default 0)

Seed list: read from data/seed-urls.json when present (T2), otherwise a
curated fallback (homepage + top-level pages) is used so the harness is
immediately runnable.

Design rules:
  - NON-DESTRUCTIVE: no form submissions, no POSTs, no newsletter fills.
  - Bot protection is DETECTED and recorded, never bypassed.
  - One failed page never aborts the run; failures are recorded per-URL.
  - navigation: domcontentloaded + 10s-capped networkidle + 1.5s settle
    (networkidle alone hangs on this Next.js site — see learnings.md).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EVIDENCE_DIR = ROOT / "evidence"
FINDINGS_PATH = DATA_DIR / "findings.json"
MANIFEST_PATH = DATA_DIR / "crawl-manifest.json"
SEED_URLS_PATH = DATA_DIR / "seed-urls.json"

NAV_TIMEOUT_MS = 30_000          # hard cap for page.goto
NETWORKIDLE_CAP_MS = 10_000      # networkidle is "discouraged" + flaky on Next.js
SETTLE_MS = 1500                 # post-load hydration/render settle window
POLITE_DELAY_RANGE = (0.5, 1.5)  # seconds between pages

DESKTOP_VIEWPORT = {"width": 1920, "height": 1080}

# CLI device key -> (manifest label, evidence dir slug, mobile preset or None)
DEVICE_ALIASES = {
    "desktop": ("desktop", "desktop", None),
    "iphone-13": ("iPhone 13", "iphone-13", "iPhone 13"),
    "pixel-7": ("Pixel 7", "pixel-7", "Pixel 7"),
}
MOBILE_PRESETS = ("iPhone 13", "Pixel 7")

# Curated fallback when T2's data/seed-urls.json is absent (pages sitemap).
FALLBACK_URLS = [
    "https://www.injector.world/",
    "https://www.injector.world/clinics",
    "https://www.injector.world/states",
    "https://www.injector.world/services",
    "https://www.injector.world/brands",
    "https://www.injector.world/guides",
    "https://www.injector.world/news",
    "https://www.injector.world/how-we-verify",
    "https://www.injector.world/editorial-standards",
    "https://www.injector.world/medical-advisory",
    "https://www.injector.world/about",
    "https://www.injector.world/list-your-practice",
    "https://www.injector.world/contact",
    "https://www.injector.world/privacy",
    "https://www.injector.world/terms",
    "https://www.injector.world/hipaa",
]

# Phrases that unambiguously mark a consent/cookie accept button. Keep
# conservative — we never guess at interactive elements.
_CONSENT_PHRASES = (
    "accept all",
    "accept",
    "agree",
    "allow all",
    "allow",
    "got it",
    "i understand",
    "consent",
    "ok",
)
_CONSENT_RE = re.compile(
    r"^(accept all|accept|agree|allow all|allow|got it|i understand|consent|ok)$",
    re.IGNORECASE,
)
_CHALLENGE_WORDS = ("challenge", "captcha")


# --------------------------------------------------------------------------
# JSON helpers (append-only, atomic write)
# --------------------------------------------------------------------------
def _read_json_list(path: Path) -> list:
    """Return the JSON array at path, or [] if absent/corrupt/not-an-array."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_json_list(path: Path, entries: list) -> None:
    """Atomically write a JSON array (tmp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------
# Evidence helpers
# --------------------------------------------------------------------------
def _page_slug(url: str) -> str:
    """Filesystem-safe slug for a URL; 'home' for the site root."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "home"
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return slug or "home"


def _device_slug(device: str) -> str:
    """'desktop' | 'iphone-13' | 'pixel-7' from the manifest device label."""
    return device.lower().replace(" ", "-")


def _timestamp() -> str:
    """Filesystem-safe timestamp for screenshot filenames."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Contexts
# --------------------------------------------------------------------------
def desktop_context(browser):
    """Desktop context: 1920x1080, scale 1, en-US locale."""
    return browser.new_context(
        viewport=dict(DESKTOP_VIEWPORT),
        device_scale_factor=1,
        locale="en-US",
    )


_DEVICE_CACHE: dict[str, dict] = {}


def _preset(device_name: str) -> dict:
    """Return a cached device descriptor, resolving via a short-lived
    sync_playwright if not yet cached. Must be called OUTSIDE an active
    sync_playwright context (nesting is forbidden by the sync API)."""
    if device_name not in _DEVICE_CACHE:
        with sync_playwright() as p:
            _DEVICE_CACHE[device_name] = dict(p.devices[device_name])
    return _DEVICE_CACHE[device_name]


def mobile_context(browser, device_name: str):
    """Mobile emulation via Playwright device presets (iPhone 13 / Pixel 7)."""
    if device_name not in MOBILE_PRESETS:
        raise ValueError(
            f"unknown mobile preset {device_name!r}; expected one of {MOBILE_PRESETS}"
        )
    return browser.new_context(**dict(_preset(device_name)), locale="en-US")


# --------------------------------------------------------------------------
# Banner / dialog handling
# --------------------------------------------------------------------------
def dismiss_banners(page) -> bool:
    """Best-effort consent/cookie banner dismissal. Returns True if dismissed.

    Only clicks elements whose accessible text exactly matches a conservative
    consent-phrase allowlist. Never touches anything else. Non-destructive.
    """
    candidates = page.locator("button, a, [role='button']")
    count = min(candidates.count(), 25)
    for i in range(count):
        el = candidates.nth(i)
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text() or "").strip()
        except PlaywrightError:
            continue
        if _CONSENT_RE.match(text):
            try:
                el.click(timeout=3000)
                return True
            except PlaywrightError:
                continue
    return False


def _is_bot_blocked(status, title, body_sample, resp_headers) -> bool:
    """Detect bot-protection without attempting to bypass it."""
    if status in (403, 503):
        return True
    haystack = f"{title} {body_sample}".lower()
    if any(w in haystack for w in _CHALLENGE_WORDS):
        return True
    cf_headers = [k for k in (resp_headers or {}) if k.lower().startswith("cf-")]
    if cf_headers:
        # cf-ray alone appears on most Cloudflare-fronted sites; only treat
        # it as blocking when paired with a mitigation marker or a >=400 status.
        mitigated = str((resp_headers or {}).get("cf-mitigated", "")).lower()
        if mitigated == "challenge":
            return True
        if status is not None and status >= 400:
            return True
    return False


# --------------------------------------------------------------------------
# Core crawl
# --------------------------------------------------------------------------
def crawl_page(context, url: str, device: str) -> dict:
    """Crawl one URL, collecting evidence. Never raises on page-level failure.

    device is the canonical manifest label: 'desktop' | 'iPhone 13' | 'Pixel 7'.
    """
    entry: dict = {
        "url": url,
        "device": device,
        "status": None,
        "load_time_ms": 0,
        "title": "",
        "console_errors": [],
        "failed_requests": [],
        "broken_images": [],
        "bot_blocked": False,
        "cf_markers": [],
        "banner_dismissed": False,
        "screenshots": {"full": None, "viewport": None},
        "tested_at": _iso_now(),
        "error": None,
    }
    ts = _timestamp()
    slug = _page_slug(url)
    shot_dir = EVIDENCE_DIR / _device_slug(device) / slug
    shot_dir.mkdir(parents=True, exist_ok=True)

    page = context.new_page()

    # Dialogs (alert/confirm/geolocation-adjacent prompts): always dismiss.
    page.on("dialog", lambda d: d.dismiss())

    console_errors: list[str] = []
    failed_requests: list[dict] = []

    def _on_console(msg):
        if msg.type == "error":
            console_errors.append(f"{msg.type}: {msg.text}")

    def _on_requestfailed(req):
        failed_requests.append({"url": req.url, "error": req.failure})

    page.on("console", _on_console)
    page.on("requestfailed", _on_requestfailed)

    resp = None
    try:
        # domcontentloaded first (networkidle alone hangs on Next.js)...
        resp = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        # ...then best-effort capped networkidle (timeout = "loaded enough")...
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
        except PlaywrightTimeoutError:
            pass
        # ...then a settle window for hydration/render.
        page.wait_for_timeout(SETTLE_MS)

        entry["status"] = resp.status if resp else None

        # Load timing from Navigation Timing API.
        try:
            nav = page.evaluate("performance.getEntriesByType('navigation')[0]")
            entry["load_time_ms"] = int(nav.get("loadEventEnd") or 0) if nav else 0
        except PlaywrightError:
            entry["load_time_ms"] = 0

        entry["title"] = page.title()
        resp_headers = resp.headers if resp else {}

        # Broken images.
        try:
            entry["broken_images"] = page.evaluate(
                """Array.from(document.images)
                    .filter(img => img.complete && img.naturalWidth === 0)
                    .map(img => img.src || img.currentSrc)"""
            )
        except PlaywrightError:
            entry["broken_images"] = []

        # Bot-blocked detection (record-only, never bypass).
        body_sample = ""
        try:
            body_sample = page.locator("body").inner_text(timeout=5000)[:2000]
        except PlaywrightError:
            body_sample = ""
        entry["bot_blocked"] = _is_bot_blocked(
            entry["status"], entry["title"], body_sample, resp_headers
        )
        entry["cf_markers"] = sorted(
            {k for k in resp_headers if k.lower().startswith("cf-")}
        )

        # Consent/cookie banner: dismiss if present (log only).
        entry["banner_dismissed"] = dismiss_banners(page)
        if entry["banner_dismissed"]:
            print(f"  [banner] dismissed consent/cookie banner on {url}")

        # Screenshots: full-page + viewport.
        full_path = shot_dir / f"{ts}-full.png"
        view_path = shot_dir / f"{ts}-viewport.png"
        page.screenshot(path=str(full_path), full_page=True)
        page.screenshot(path=str(view_path), full_page=False)
        entry["screenshots"]["full"] = str(full_path)
        entry["screenshots"]["viewport"] = str(view_path)

    except PlaywrightTimeoutError as exc:
        entry["error"] = f"navigation timeout: {exc}"
    except PlaywrightError as exc:
        entry["error"] = f"playwright error: {exc}"
    except Exception as exc:  # noqa: BLE001 - never abort the run on one page
        entry["error"] = f"unexpected error: {exc!r}"
    finally:
        entry["console_errors"] = console_errors
        entry["failed_requests"] = failed_requests
        page.close()

    return entry


# --------------------------------------------------------------------------
# Findings + manifest records
# --------------------------------------------------------------------------
def append_finding(
    device: str,
    url: str,
    severity: str,
    title: str,
    actual: str,
    expected: str,
    repro_steps: str,
    screenshot_path: str = "",
    notes: str = "",
    affected_pages: list | None = None,
) -> dict:
    """Append one finding to data/findings.json (JSON array, append-only)."""
    entry = {
        "id": f"{_device_slug(device)}-{_timestamp()}-{len(_read_json_list(FINDINGS_PATH)) + 1}",
        "device": device,
        "url": url,
        "severity": severity,
        "title": title,
        "actual": actual,
        "expected": expected,
        "repro_steps": repro_steps,
        "screenshot_path": screenshot_path,
        "notes": notes,
        "affected_pages": affected_pages or [],
        "created_at": _iso_now(),
    }
    entries = _read_json_list(FINDINGS_PATH)
    entries.append(entry)
    _write_json_list(FINDINGS_PATH, entries)
    return entry


def update_manifest(entry: dict) -> None:
    """Append one crawl record to data/crawl-manifest.json (append-only)."""
    record = {
        "url": entry["url"],
        "device": entry["device"],
        "status": entry["status"],
        "load_time_ms": entry["load_time_ms"],
        "console_errors": len(entry["console_errors"]),
        "broken_images": entry["broken_images"],
        "issues": _summarize_issues(entry),
        "tested_at": entry["tested_at"],
        "bot_blocked": entry["bot_blocked"],
    }
    records = _read_json_list(MANIFEST_PATH)
    records.append(record)
    _write_json_list(MANIFEST_PATH, records)


def _summarize_issues(entry: dict) -> list[str]:
    issues = []
    n_console = len(entry["console_errors"])
    n_failed = len(entry["failed_requests"])
    n_broken = len(entry["broken_images"])
    if n_console:
        issues.append(f"{n_console} console error(s)")
    if n_failed:
        issues.append(f"{n_failed} failed request(s)")
    if n_broken:
        issues.append(f"{n_broken} broken image(s)")
    if entry.get("error"):
        issues.append(entry["error"])
    if entry["bot_blocked"]:
        issues.append("bot protection suspected")
    return issues


# --------------------------------------------------------------------------
# Seed list loading
# --------------------------------------------------------------------------
def load_seed_urls(explicit: list[str] | None = None) -> list[str]:
    """URLs to crawl: explicit args > data/seed-urls.json > fallback list."""
    if explicit:
        return explicit
    if SEED_URLS_PATH.exists():
        try:
            data = json.loads(SEED_URLS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return [str(u) for u in data]
            print(
                f"warning: {SEED_URLS_PATH} not a non-empty list; using fallback",
                file=sys.stderr,
            )
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"warning: cannot read {SEED_URLS_PATH} ({exc}); using fallback",
                file=sys.stderr,
            )
    else:
        print(
            f"info: {SEED_URLS_PATH} not found (T2 pending); using fallback list",
            file=sys.stderr,
        )
    return list(FALLBACK_URLS)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _resolve_device(alias: str) -> tuple[str, str, str | None]:
    if alias not in DEVICE_ALIASES:
        raise SystemExit(
            f"error: unknown device {alias!r}; choose from {sorted(DEVICE_ALIASES)}"
        )
    return DEVICE_ALIASES[alias]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("device", choices=sorted(DEVICE_ALIASES), help="device profile")
    ap.add_argument("urls", nargs="*", help="explicit URLs to crawl (overrides seed list)")
    ap.add_argument("--headless", action="store_true", default=True, help=argparse.SUPPRESS)
    ap.add_argument("--headed", action="store_true", help="run with a visible browser window")
    ap.add_argument("--slowmo", type=int, default=0, metavar="MS", help="pause between actions in ms (default 0)")
    args = ap.parse_args(argv)

    label, dev_slug, preset = _resolve_device(args.device)
    urls = load_seed_urls(args.urls or None)

    # Resolve device presets up front so a bad preset name fails fast AND the
    # descriptor cache is warm before any sync_playwright context opens
    # (mobile_context must never open a nested one).
    if preset:
        try:
            preset_desc = dict(_preset(preset))
        except KeyError:
            print(
                f"error: preset {preset!r} missing from playwright.devices",
                file=sys.stderr,
            )
            return 2
    else:
        preset_desc = None

    with sync_playwright() as p:
        if preset_desc:
            vp = preset_desc.get("viewport", {})
            print(
                f"device : {label} ({preset}) viewport={vp.get('width')}x{vp.get('height')}"
            )
        else:
            print(f"device : {label} ({DESKTOP_VIEWPORT['width']}x{DESKTOP_VIEWPORT['height']})")
        print(f"urls   : {len(urls)} -> {urls[0] if urls else '(none)'}")

        browser = p.chromium.launch(headless=not args.headed, slow_mo=args.slowmo)
        context = (
            desktop_context(browser) if not preset else mobile_context(browser, preset)
        )

        ok_urls = failed_urls = 0
        try:
            for i, url in enumerate(urls, start=1):
                print(f"[{i}/{len(urls)}] {url}")
                entry = crawl_page(context, url, label)
                update_manifest(entry)
                if entry["error"] or entry["status"] is None:
                    failed_urls += 1
                    print(
                        f"  status: n/a  load: n/a  error: {entry['error']}",
                        file=sys.stderr,
                    )
                else:
                    ok_urls += 1
                    print(
                        f"  status: {entry['status']}  "
                        f"load: {entry['load_time_ms']}ms  "
                        f"console_errors: {len(entry['console_errors'])}  "
                        f"failed_reqs: {len(entry['failed_requests'])}  "
                        f"broken_images: {len(entry['broken_images'])}  "
                        f"bot_blocked: {entry['bot_blocked']}"
                    )
                # Polite delay between pages (not after the last one).
                if i < len(urls):
                    time.sleep(random.uniform(*POLITE_DELAY_RANGE))
        finally:
            context.close()
            browser.close()

    print(f"\nmanifest: {MANIFEST_PATH} ({len(_read_json_list(MANIFEST_PATH))} entries)")
    print(f"crawl complete: {ok_urls} ok, {failed_urls} failed (device={label})")
    return 1 if failed_urls == len(urls) else 0


if __name__ == "__main__":
    sys.exit(main())
