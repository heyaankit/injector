#!/usr/bin/env python3
"""Interaction-capable full-crawl UX harness for the injector.world UX audit.

Fresh crawl for the UX audit. Does NOT reuse QA manifest data; writes ONLY to
`evidence/ux/` and `data/ux-manifest.json`. Never touches QA `evidence/`.

Usage:
    python scripts/ux_harness.py desktop|iphone-13|pixel-7 [--urls FILE] [--discover] [--validate]

Modes:
    default      Full crawl of the URL list (from --urls FILE, else data/ux-coverage.json
                 tested pages, else data/seed-urls.json) with base crawl + interaction probes.
    --validate   Probe crawl of the homepage on the given device; produces >=1 screenshot.
    --discover   After crawling, collect internal <a href> across crawled pages, diff against
                 data/ux-coverage.json, and record the bounded delta into its `discovery` section.

Design rules (inherited from scripts/harness.py):
  - NON-DESTRUCTIVE: forms get INVALID/empty data only, never valid submissions.
  - Bot protection is DETECTED and recorded, never bypassed.
  - One failed page never aborts the run; failures are recorded per-URL.
  - navigation: domcontentloaded + 10s-capped networkidle + 1.5s settle.
  - Do NOT touch /admin/ or /api/; do NOT auto-crawl the 12,939-URL dynamic surface.
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
EVIDENCE_DIR = ROOT / "evidence" / "ux"
MANIFEST_PATH = DATA_DIR / "ux-manifest.json"
COVERAGE_PATH = DATA_DIR / "ux-coverage.json"
SEED_URLS_PATH = DATA_DIR / "seed-urls.json"

NAV_TIMEOUT_MS = 30_000
NETWORKIDLE_CAP_MS = 10_000
SETTLE_MS = 1500
POLITE_DELAY_RANGE = (0.5, 1.5)

DESKTOP_VIEWPORT = {"width": 1920, "height": 1080}
BASE = "https://www.injector.world"

# CLI device key -> (manifest label, evidence dir slug, mobile preset or None)
DEVICE_ALIASES = {
    "desktop": ("desktop", "desktop", None),
    "iphone-13": ("iPhone 13", "iphone-13", "iPhone 13"),
    "pixel-7": ("Pixel 7", "pixel-7", "Pixel 7"),
}
MOBILE_PRESETS = ("iPhone 13", "Pixel 7")

# Discovery bounds: never crawl the dynamic auto-sitemap surface; cap the
# recorded delta and the sample added to coverage.
DISCOVERY_FOUND_CAP = 20
DISCOVERY_SAMPLE_CAP = 10
DYNAMIC_MARKERS = ("/sitemaps/", "/sitemap", "/api/", "/admin/", "/_next/")

_CONSENT_RE = re.compile(
    r"^(accept all|accept|agree|allow all|allow|got it|i understand|consent|ok)$",
    re.IGNORECASE,
)
_CHALLENGE_WORDS = ("challenge", "captcha")


# --------------------------------------------------------------------------
# JSON helpers (append-only, atomic write)
# --------------------------------------------------------------------------
def _read_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_json_list(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json_obj(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_obj(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------
def _page_slug(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return "home"
    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return slug or "home"


def _device_slug(device: str) -> str:
    return device.lower().replace(" ", "-")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Contexts
# ---------------------------------------------------------------------------
def desktop_context(browser):
    return browser.new_context(
        viewport=dict(DESKTOP_VIEWPORT),
        device_scale_factor=1,
        locale="en-US",
    )


_DEVICE_CACHE: dict[str, dict] = {}


def _preset(device_name: str) -> dict:
    if device_name not in _DEVICE_CACHE:
        with sync_playwright() as p:
            _DEVICE_CACHE[device_name] = dict(p.devices[device_name])
    return _DEVICE_CACHE[device_name]


def mobile_context(browser, device_name: str):
    if device_name not in MOBILE_PRESETS:
        raise ValueError(
            f"unknown mobile preset {device_name!r}; expected one of {MOBILE_PRESETS}"
        )
    return browser.new_context(**dict(_preset(device_name)), locale="en-US")


# ---------------------------------------------------------------------------
# Banner / bot handling (reused from harness.py)
# ---------------------------------------------------------------------------
def dismiss_banners(page) -> bool:
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
    if status in (403, 503):
        return True
    haystack = f"{title} {body_sample}".lower()
    if any(w in haystack for w in _CHALLENGE_WORDS):
        return True
    cf_headers = [k for k in (resp_headers or {}) if k.lower().startswith("cf-")]
    if cf_headers:
        mitigated = str((resp_headers or {}).get("cf-mitigated", "")).lower()
        if mitigated == "challenge":
            return True
        if status is not None and status >= 400:
            return True
    return False


# ---------------------------------------------------------------------------
# Base crawl (reused pattern from harness.py, writes to evidence/ux/)
# ---------------------------------------------------------------------------
def crawl_page(context, url: str, device: str) -> dict:
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
        resp = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(SETTLE_MS)

        entry["status"] = resp.status if resp else None
        try:
            nav = page.evaluate("performance.getEntriesByType('navigation')[0]")
            entry["load_time_ms"] = int(nav.get("loadEventEnd") or 0) if nav else 0
        except PlaywrightError:
            entry["load_time_ms"] = 0
        entry["title"] = page.title()
        resp_headers = resp.headers if resp else {}

        try:
            entry["broken_images"] = page.evaluate(
                """Array.from(document.images)
                    .filter(img => img.complete && img.naturalWidth === 0)
                    .map(img => img.src || img.currentSrc)"""
            )
        except PlaywrightError:
            entry["broken_images"] = []

        body_sample = ""
        try:
            body_sample = page.locator("body").inner_text(timeout=5000)[:2000]
        except PlaywrightError:
            body_sample = ""
        entry["bot_blocked"] = _is_bot_blocked(
            entry["status"], entry["title"], body_sample, resp_headers
        )

        entry["banner_dismissed"] = dismiss_banners(page)
        if entry["banner_dismissed"]:
            print(f"  [banner] dismissed consent/cookie banner on {url}")

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
    except Exception as exc:  # noqa: BLE001
        entry["error"] = f"unexpected error: {exc!r}"
    finally:
        entry["console_errors"] = console_errors
        entry["failed_requests"] = failed_requests
        page.close()

    return entry


# ---------------------------------------------------------------------------
# Interaction probes (modeled on legacy/scripts-t11/t11_mobile_functional.py)
# ---------------------------------------------------------------------------
def _shot(page, shot_dir: Path, step: str, ts: str, full_page: bool = False) -> str:
    p = shot_dir / f"{step}-{ts}.png"
    try:
        page.screenshot(path=str(p), full_page=full_page)
    except Exception:  # noqa: BLE001
        return ""
    return str(p)


def probe_menus(page, shot_dir: Path, ts: str, is_mobile: bool) -> list:
    """(a) menus/dropdowns: open each nav dropdown/menu, capture, close.
    On mobile, open the hamburger and capture as-is (no overlap workaround)."""
    shots = []
    if is_mobile:
        burger = page.locator(
            "header button[aria-label='Open menu'], header button[aria-label='Close menu']"
        )
        if burger.count():
            try:
                burger.first.click()
                page.wait_for_timeout(1500)
                shots.append(_shot(page, shot_dir, "menu-hamburger-open", ts))
            except PlaywrightError:
                pass
        return shots
    # Desktop: open each nav dropdown (hover to reveal), capture, close.
    dropdowns = page.evaluate(
        """() => {
            const h = document.querySelector('header');
            if (!h) return [];
            const seen = new Set();
            const out = [];
            h.querySelectorAll('nav a, nav button, [role=menuitem], [aria-haspopup]').forEach(el => {
                const t = (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 30);
                if (t && !seen.has(t)) { seen.add(t); out.push(t); }
            });
            return out.slice(0, 4);
        }"""
    )
    for label in dropdowns:
        try:
            loc = page.locator(
                f"header nav a:has-text('{label}'), header nav button:has-text('{label}')"
            ).first
            loc.hover()
            page.wait_for_timeout(900)
            shots.append(_shot(page, shot_dir, f"menu-open-{_slug(label)}", ts))
            # close by pressing Escape
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        except PlaywrightError:
            continue
    return shots


def probe_forms(page, shot_dir: Path, ts: str) -> list:
    """(b) forms: click into each field, type INVALID/empty data only, capture."""
    shots = []
    # Newsletter
    nl = page.locator("form:has(#nl-email)")
    if nl.count():
        try:
            nl.locator("#nl-email").fill("not-an-email")
            try:
                nl.get_by_role("button", name="Subscribe").click()
            except PlaywrightError:
                nl.locator("button[type=submit], button").first.click()
            page.wait_for_timeout(1500)
            shots.append(_shot(page, shot_dir, "form-newsletter-invalid", ts))
            nl.locator("#nl-email").fill("")
            try:
                nl.get_by_role("button", name="Subscribe").click()
            except PlaywrightError:
                nl.locator("button[type=submit], button").first.click()
            page.wait_for_timeout(1500)
            shots.append(_shot(page, shot_dir, "form-newsletter-empty", ts))
        except PlaywrightError:
            pass
    # Search hero
    hero = page.locator("form:has(input[placeholder='Service, injector, or clinic'])")
    if hero.count():
        try:
            hero.locator("input").first.fill("zzz-invalid")
            hero.locator("input").first.press("Enter")
            page.wait_for_timeout(2500)
            shots.append(_shot(page, shot_dir, "form-search-invalid", ts))
        except PlaywrightError:
            pass
    # Generic: click into each visible input, type invalid, capture validation.
    inputs = page.locator("input:visible, textarea:visible")
    n = min(inputs.count(), 5)
    for i in range(n):
        try:
            inp = inputs.nth(i)
            inp.click()
            inp.fill("invalid")
            page.wait_for_timeout(600)
            shots.append(_shot(page, shot_dir, f"form-field-{i}-invalid", ts))
        except PlaywrightError:
            continue
    return shots


def probe_buttons(page, shot_dir: Path, ts: str, is_mobile: bool) -> list:
    """(c) buttons/CTAs: hover (desktop) + click primary CTAs, verify something happens."""
    shots = []
    ctas = page.evaluate(
        """() => {
            const els = Array.from(document.querySelectorAll('a[href], button'));
            const seen = new Set(); const out = [];
            els.forEach(e => {
                const t = (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
                if (!t || seen.has(t)) return;
                const cls = (e.className || '').toString();
                if (/btn|cta|button|primary/i.test(cls) || /find|view|learn|get started|book|search/i.test(t)) {
                    seen.add(t); out.push({text: t, tag: e.tagName});
                }
            });
            return out.slice(0, 3);
        }"""
    )
    for c in ctas:
        try:
            loc = page.locator(
                f"{c['tag'].lower()}:has-text('{c['text']}')"
            ).first
            if not is_mobile:
                loc.hover()
                page.wait_for_timeout(700)
                shots.append(_shot(page, shot_dir, f"cta-hover-{_slug(c['text'])}", ts))
            before = page.url
            loc.click()
            page.wait_for_timeout(2500)
            after = page.url
            shots.append(_shot(page, shot_dir, f"cta-click-{_slug(c['text'])}", ts))
            # verify something happened (navigation or state change)
            if after != before:
                page.go_back()
                page.wait_for_timeout(2000)
        except PlaywrightError:
            continue
    return shots


def probe_scroll(page, shot_dir: Path, ts: str) -> list:
    """(d) scrolling: scroll to bottom, capture, check sticky header behavior."""
    shots = []
    try:
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(600)
        shots.append(_shot(page, shot_dir, "scroll-mid", ts))
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1200)
        shots.append(_shot(page, shot_dir, "scroll-bottom", ts))
        # sticky header check
        sticky = page.evaluate(
            """() => {
                const h = document.querySelector('header');
                if (!h) return null;
                const cs = getComputedStyle(h);
                return {position: cs.position, top: cs.top, zIndex: cs.zIndex};
            }"""
        )
        return shots, sticky
    except PlaywrightError:
        return shots, None


def probe_hover(page, shot_dir: Path, ts: str) -> list:
    """(e) hover states (desktop only): primary nav item + a card."""
    shots = []
    try:
        page.locator("header nav a").first.hover()
        page.wait_for_timeout(700)
        shots.append(_shot(page, shot_dir, "hover-nav", ts))
    except PlaywrightError:
        pass
    try:
        card = page.locator("a[href*='/clinics/'], a[href*='/brands/'], a[href*='/guides/']").first
        card.hover()
        page.wait_for_timeout(700)
        shots.append(_shot(page, shot_dir, "hover-card", ts))
    except PlaywrightError:
        pass
    return shots


def probe_responsive(page, shot_dir: Path, ts: str) -> list:
    """Responsive spot-checks (desktop only): resize viewport, capture, restore."""
    shots = []
    for w in (1366, 1024, 768):
        try:
            page.set_viewport_size({"width": w, "height": 1080})
            page.wait_for_timeout(800)
            shots.append(_shot(page, shot_dir, f"responsive-{w}", ts))
        except PlaywrightError:
            continue
    try:
        page.set_viewport_size(dict(DESKTOP_VIEWPORT))
    except PlaywrightError:
        pass
    return shots


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40] or "item"


# ---------------------------------------------------------------------------
# Probe orchestration
# ---------------------------------------------------------------------------
def run_probes(page, url: str, device: str, is_mobile: bool) -> dict:
    """Run interaction probes appropriate to the page. Returns probe evidence."""
    ts = _timestamp()
    shot_dir = EVIDENCE_DIR / _device_slug(device) / _page_slug(url)
    shot_dir.mkdir(parents=True, exist_ok=True)
    probes: dict = {"menus": [], "forms": [], "buttons": [], "scroll": [], "hover": [], "responsive": []}

    # Menus/dropdowns on every page (nav is global).
    probes["menus"] = probe_menus(page, shot_dir, ts, is_mobile)

    # Forms on pages that have them.
    if page.locator("form").count():
        probes["forms"] = probe_forms(page, shot_dir, ts)

    # Buttons/CTAs on every page (bounded).
    probes["buttons"] = probe_buttons(page, shot_dir, ts, is_mobile)

    # Scrolling on key pages.
    path = urlparse(url).path
    if path in ("", "/", "/clinics", "/states") or path.startswith("/guides/") or path.startswith("/clinics/"):
        shots, sticky = probe_scroll(page, shot_dir, ts)
        probes["scroll"] = shots
        probes["sticky_header"] = sticky

    # Hover states desktop only.
    if not is_mobile:
        probes["hover"] = probe_hover(page, shot_dir, ts)
        probes["responsive"] = probe_responsive(page, shot_dir, ts)

    return probes


# ---------------------------------------------------------------------------
# Discovery pass
# ---------------------------------------------------------------------------
def _is_internal(href: str) -> bool:
    return href.startswith(BASE) and not any(m in href for m in DYNAMIC_MARKERS)


def _norm(href: str) -> str:
    return href.split("#")[0].rstrip("/") or BASE


def run_discovery(context, urls: list[str]) -> dict:
    """Collect internal <a href> across crawled pages, diff vs coverage, record bounded delta."""
    found: set[str] = set()
    for url in urls:
        page = context.new_page()
        try:
            page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(SETTLE_MS)
            hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            for h in hrefs:
                if _is_internal(h):
                    found.add(_norm(h))
        except Exception:  # noqa: BLE001
            pass
        finally:
            page.close()

    cov = _read_json_obj(COVERAGE_PATH)
    covered = {p["url"] for p in cov.get("pages", [])}
    new_urls = sorted(found - covered)
    # Bound the recorded delta.
    bounded = new_urls[:DISCOVERY_FOUND_CAP]
    # Bounded sample: first 10 unique clinic-profile or unmatched internal URLs.
    sample = []
    for u in bounded:
        if "/clinics/" in u or u not in covered:
            sample.append(u)
        if len(sample) >= DISCOVERY_SAMPLE_CAP:
            break
    # Add sample to coverage list as tested:true.
    pages = cov.setdefault("pages", [])
    existing = {p["url"] for p in pages}
    for u in sample:
        if u not in existing:
            pages.append({"url": u, "group": "discovered", "tested": True})
            existing.add(u)
    cov["discovery"] = {
        "found_urls": bounded,
        "untested_reachable": len(bounded),
        "sampled": sample,
        "last_run": _iso_now(),
    }
    _write_json_obj(COVERAGE_PATH, cov)
    return cov["discovery"]


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------
def update_manifest(entry: dict) -> None:
    record = {
        "url": entry["url"],
        "device": entry["device"],
        "status": entry["status"],
        "load_time_ms": entry["load_time_ms"],
        "console_errors": len(entry["console_errors"]),
        "broken_images": entry["broken_images"],
        "bot_blocked": entry["bot_blocked"],
        "tested_at": entry["tested_at"],
    }
    records = _read_json_list(MANIFEST_PATH)
    records.append(record)
    _write_json_list(MANIFEST_PATH, records)


# --------------------------------------------------------------------------
# URL loading
# --------------------------------------------------------------------------
def load_urls(explicit_file: str | None) -> list[str]:
    if explicit_file:
        p = Path(explicit_file)
        if not p.exists():
            print(f"error: urls file not found: {p}", file=sys.stderr)
            sys.exit(2)
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "pages" in data:
            return [str(x["url"]) for x in data["pages"] if x.get("tested")]
        if isinstance(data, list):
            return [str(u) for u in data]
        print(f"error: unrecognized urls file format: {p}", file=sys.stderr)
        sys.exit(2)
    # Default: coverage tested pages, else seed list.
    cov = _read_json_obj(COVERAGE_PATH)
    if cov.get("pages"):
        return [str(x["url"]) for x in cov["pages"] if x.get("tested")]
    if SEED_URLS_PATH.exists():
        return [str(u) for u in json.loads(SEED_URLS_PATH.read_text(encoding="utf-8"))]
    return []


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
    ap.add_argument("device", help="device profile: desktop | iphone-13 | pixel-7")
    ap.add_argument("--urls", help="JSON file of URLs to crawl (list or coverage object)")
    ap.add_argument("--discover", action="store_true", help="run discovery pass after crawl")
    ap.add_argument("--validate", action="store_true", help="probe-crawl the homepage only")
    args = ap.parse_args(argv)

    try:
        label, dev_slug, preset = _resolve_device(args.device)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if preset:
        try:
            preset_desc = dict(_preset(preset))
        except KeyError:
            print(f"error: preset {preset!r} missing from playwright.devices", file=sys.stderr)
            return 2
    else:
        preset_desc = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = desktop_context(browser) if not preset else mobile_context(browser, preset)

        if args.validate:
            url = BASE
            print(f"[validate] {label} -> {url}")
            entry = crawl_page(context, url, label)
            update_manifest(entry)
            shot_dir = EVIDENCE_DIR / dev_slug / _page_slug(url)
            shot_dir.mkdir(parents=True, exist_ok=True)
            page = context.new_page()
            try:
                page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(SETTLE_MS)
                probes = run_probes(page, url, label, bool(preset))
                n_shots = sum(len(v) for v in probes.values() if isinstance(v, list))
                print(f"  validate probes: {n_shots} screenshots")
            finally:
                page.close()
            context.close()
            browser.close()
            print(f"validate complete: {entry['status']} load={entry['load_time_ms']}ms")
            return 0

        urls = load_urls(args.urls)
        print(f"device : {label} ({dev_slug})")
        print(f"urls   : {len(urls)}")

        # Discovery mode: run the bounded discovery pass on a small sample of
        # URLs (never the full dynamic surface), then exit. No heavy probe crawl.
        if args.discover:
            sample = urls[:DISCOVERY_SAMPLE_CAP]
            print(f"[discover] crawling {len(sample)} sample URLs for internal links")
            disc = run_discovery(context, sample)
            print(f"  discovery: found_urls={len(disc['found_urls'])} "
                  f"untested_reachable={disc['untested_reachable']} "
                  f"sampled={len(disc['sampled'])}")
            context.close()
            browser.close()
            print(f"\ndiscovery complete; coverage updated: {COVERAGE_PATH}")
            return 0

        ok_urls = failed_urls = 0
        try:
            for i, url in enumerate(urls, start=1):
                print(f"[{i}/{len(urls)}] {url}")
                entry = crawl_page(context, url, label)
                update_manifest(entry)
                if entry["error"] or entry["status"] is None:
                    failed_urls += 1
                    print(f"  status: n/a  error: {entry['error']}", file=sys.stderr)
                else:
                    ok_urls += 1
                    print(
                        f"  status: {entry['status']}  load: {entry['load_time_ms']}ms  "
                        f"console_errors: {len(entry['console_errors'])}  "
                        f"broken_images: {len(entry['broken_images'])}  "
                        f"bot_blocked: {entry['bot_blocked']}"
                    )
                # Probes on the same page (reuse a fresh page).
                page = context.new_page()
                try:
                    page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(SETTLE_MS)
                    run_probes(page, url, label, bool(preset))
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    page.close()
                if i < len(urls):
                    time.sleep(random.uniform(*POLITE_DELAY_RANGE))
        finally:
            context.close()
            browser.close()

    print(f"\nmanifest: {MANIFEST_PATH} ({len(_read_json_list(MANIFEST_PATH))} entries)")
    print(f"crawl complete: {ok_urls} ok, {failed_urls} failed (device={label})")
    return 1 if failed_urls == len(urls) else 0


HOME_URL = BASE + "/"


if __name__ == "__main__":
    sys.exit(main())