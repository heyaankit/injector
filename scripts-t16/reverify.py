#!/usr/bin/env python3
"""T16 - 20% live re-verification of reported issues (injector.world QA).

Samples ~20% (>= 9) of the 44 reported issues (9 mobile + 35 desktop) via a
deterministic stratified random sample (fixed seed), then LIVE re-executes each
issue's documented repro steps against the real site in the recorded device
context and asserts the reported "actual" condition still holds.

Outputs evidence/reverification-log.json (per issue + selection metadata) and a
fresh evidence screenshot per sampled issue in evidence/reverify/{id}.png.

Design rules (from plan + learnings):
  - Non-destructive: no form submits, no POSTs, no /admin/ or /api/.
  - Mobile via Playwright device presets (iPhone 13 / Pixel 7), desktop 1920x1080.
  - Never nest sync_playwright (warm harness._preset cache first).
  - DOM assertions only (model cannot view images); screenshots are evidence.
  - One page per check, sequential, polite delays.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import harness  # noqa: E402

FINDINGS_PATH = ROOT / "data" / "findings.json"
REVERIFY_DIR = ROOT / "evidence" / "reverify"
LOG_PATH = ROOT / "evidence" / "reverification-log.json"

SAMPLE_SEED = 20260801
MOBILE_DEVICE = "iPhone 13"

# Fixed, deterministic sample (chosen by the selection logic in this module,
# asserted at runtime so the log always matches the code).
EXPECTED_SAMPLE = [
    "mobile-t9-1785640579-51",   # M-001 CRITICAL misleading clinic-count claim
    "mobile-t11-1785642385-2",   # M-003 HIGH nav-menu overlap
    "mobile-t11-1785642385-3",   # M-008 MEDIUM footer tap interception
    "desktop-20260801-180803-44",  # D-001 CRITICAL misleading claim + test clinics
    "desktop-20260801-175239-33",  # D-012 HIGH broken nav /services/dysport
    "desktop-20260801-175103-17",  # D-004 HIGH broken nav /guides/botox-vs-filler
    "desktop-20260801-174829-4",   # D-018 MEDIUM unlabeled controls /services
    "desktop-20260801-174926-8",   # D-022 MEDIUM unlabeled controls /how-we-verify
    "desktop-20260801-174940-9",   # D-023 MEDIUM unlabeled controls /editorial-standards
    "desktop-t6-1785611129-1",     # D-035 LOW duplicate newsletter signup
]

NAV_TIMEOUT_MS = 30_000
NETWORKIDLE_CAP_MS = 10_000
SETTLE_MS = 1500


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_mobile_dev(dev: str) -> bool:
    d = (dev or "").lower()
    return "iphone" in d or "pixel" in d or d == "mobile"


def select_sample() -> list[dict]:
    """Deterministic stratified random sample of the reported issues.

    Reported set = exactly what the reports did (device mobile -> iphone/pixel;
    desktop -> desktop; status != not_reproducible; kind != performance).
    Guarantees >=1 mobile + >=1 desktop and >=1 issue per severity bucket that
    exists in the combined set (CRITICAL/HIGH/MEDIUM/LOW). Fixed seed.
    """
    import random

    d = json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))
    mobile = [f for f in d if _is_mobile_dev(f.get("device")) and f.get("status") != "not_reproducible" and f.get("kind") != "performance"]
    desktop = [f for f in d if (f.get("device") or "").lower() == "desktop" and f.get("status") != "not_reproducible" and f.get("kind") != "performance"]

    def pick(items, n, rng):
        return rng.sample(items, n)

    rng = random.Random(SAMPLE_SEED)
    m_crit = [f for f in mobile if f["severity"] == "CRITICAL"]
    m_high = [f for f in mobile if f["severity"] == "HIGH"]
    m_med = [f for f in mobile if f["severity"] == "MEDIUM"]
    d_crit = [f for f in desktop if f["severity"] == "CRITICAL"]
    d_high = [f for f in desktop if f["severity"] == "HIGH"]
    d_med = [f for f in desktop if f["severity"] == "MEDIUM"]
    d_low = [f for f in desktop if f["severity"] == "LOW"]

    sample = (
        m_crit
        + pick(m_high, 1, rng)
        + pick(m_med, 1, rng)
        + d_crit
        + pick(d_high, 2, rng)
        + pick(d_med, 3, rng)
        + d_low
    )
    ids = [f["id"] for f in sample]
    assert ids == EXPECTED_SAMPLE, f"sample drift: {ids}"
    return sample


def open_page(ctx, url: str):
    """goto(domcontentloaded) -> capped networkidle -> settle -> dismiss banners."""
    page = ctx.new_page()
    page.on("dialog", lambda d: d.dismiss())
    resp = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
    except Exception:
        pass
    page.wait_for_timeout(SETTLE_MS)
    harness.dismiss_banners(page)
    page.wait_for_timeout(500)
    return page, resp


def close_page(page):
    try:
        page.close()
    except Exception:
        pass


class Retryable(Exception):
    pass


def capture(page, fid):
    """Screenshot must be taken before the page closes (handlers close in finally)."""
    try:
        path = REVERIFY_DIR / f"{fid}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path) if path.exists() else None
    except Exception:
        return None


def scroll_collect(page, steps: int = 8, wait_ms: int = 1500) -> str:
    """Scroll through the whole page collecting body innerText at each stop
    (count-up animations fire when their section scrolls into view)."""
    texts = []
    h = page.evaluate("document.body.scrollHeight")
    for i in range(steps + 1):
        page.evaluate(f"window.scrollTo(0, {int(h * i / steps)})")
        page.wait_for_timeout(wait_ms)
        texts.append(page.locator("body").inner_text(timeout=5000))
    return "\n".join(texts)


def check_m001(ctx, issue):
    """M-001 CRITICAL: homepage claims 17,020+ clinics while directory shows empty state."""
    page, resp = open_page(ctx, "https://www.injector.world/")
    try:
        status = resp.status if resp else None
        body = scroll_collect(page)
        has_17020 = "17,020" in body
        empty_state = "No verified clinics or injectors match." in body
        reproduced = bool(has_17020 and empty_state)
        observed = {
            "http_status": status,
            "stats_band_17020_present": has_17020,
            "directory_empty_state_present": empty_state,
        }
        return reproduced, observed
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_d001(ctx, issue):
    """D-001 CRITICAL: homepage claims 17,020+ / 12,400+ injectors while directory
    shows zero results AND featured clinics include test fixtures."""
    page, resp = open_page(ctx, "https://www.injector.world/")
    try:
        status = resp.status if resp else None
        body = scroll_collect(page, steps=10, wait_ms=1500)
        has_17020 = "17,020" in body
        has_12400 = "12,400" in body
        empty_state = "No verified clinics or injectors match." in body
        fixtures = [n for n in ["Test Clinic", "ABCD Clinic", "Rishav's Clinic"] if n in body]
        reproduced = bool(has_17020 and empty_state)
        observed = {
            "http_status": status,
            "stats_band_17020_present": has_17020,
            "hero_12400_present": has_12400,
            "directory_empty_state_present": empty_state,
            "test_fixtures_found": fixtures,
        }
        return reproduced, observed
    finally:
        capture(page, issue["id"])
        close_page(page)


def _nav_menu_probe(page, hrefs) -> dict:
    """Open hamburger menu on mobile, probe coverage of the given panel links."""
    toggle = page.locator("button[aria-label='Open menu']").first
    toggle.wait_for(state="visible", timeout=25000)
    toggle.click(timeout=8000)
    page.wait_for_timeout(1200)
    for href in hrefs:
        loc = page.locator(f"a[href='{href}']")
        for _ in range(12):
            try:
                if loc.count() and any(loc.nth(i).is_visible() for i in range(min(loc.count(), 6))):
                    break
            except Exception:
                pass
            page.wait_for_timeout(500)
        else:
            raise Retryable(f"panel link {href} not visible after opening menu")
    page.wait_for_timeout(800)
    probes = []
    for href in hrefs:
        loc = page.locator(f"a[href='{href}']")
        target = None
        for i in range(loc.count()):
            try:
                if loc.nth(i).is_visible():
                    bb = loc.nth(i).bounding_box()
                    if bb and bb["width"] > 0 and bb["height"] > 0:
                        target = loc.nth(i)
                        break
            except Exception:
                continue
        if target is None:
            raise Retryable(f"no visible {href} link after menu open")
        box = target.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        if cy < 0 or cy > page.evaluate("window.innerHeight"):
            raise Retryable(f"{href} center off-viewport ({cx:.0f},{cy:.0f})")
        hit = page.evaluate(
            """([x, y]) => {
                const e = document.elementFromPoint(x, y);
                if (!e) return null;
                return {
                    tag: e.tagName,
                    text: (e.innerText || '').trim().slice(0, 60),
                    href: e.getAttribute('href'),
                    cls: typeof e.className === 'string' ? e.className.slice(0, 60) : ''
                };
            }""",
            [cx, cy],
        )
        if hit is None:
            raise Retryable(f"elementFromPoint null at {href} center ({cx:.0f},{cy:.0f})")
        url_before = page.url
        page.mouse.click(cx, cy)
        page.wait_for_timeout(1500)
        hit_is_link = hit.get("tag") == "A" and (hit.get("href") or "") == href
        navigated = page.url.rstrip("/").endswith(href.rstrip("/"))
        probes.append({
            "href": href,
            "link_center": [round(cx, 1), round(cy, 1)],
            "element_from_point": hit,
            "covered": not hit_is_link,
            "navigated": navigated,
            "url_after": page.url,
        })
    return {"probes": probes}


def check_m003(ctx, issue):
    """M-003 HIGH: nav menu treatment links covered by overlapping content."""
    page, resp = open_page(ctx, "https://www.injector.world/")
    try:
        probe = _nav_menu_probe(page, ["/brands/botox", "/brands/sculptra"])
        probes = probe["probes"]
        any_covered = any(p["covered"] for p in probes)
        any_no_nav = any(not p["navigated"] for p in probes)
        reproduced = bool(any_covered or any_no_nav)
        probe["reproduced"] = reproduced
        probe["reproduced_by"] = "panel link(s) covered / tap failed to navigate"
        return reproduced, probe
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_m008(ctx, issue):
    """M-008 MEDIUM: footer link taps intercepted by overlapping content."""
    page, resp = open_page(ctx, "https://www.injector.world/")
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        footer = page.locator("footer").first
        footer.scroll_into_view_if_needed(timeout=5000)
        page.wait_for_timeout(800)
        probes = []
        for text, href in [("List your practice", "/list-your-practice"),
                           ("Cheek Filler", "/services/cheek-filler"),
                           ("Jawline Filler", "/services/jawline-filler")]:
            cand = footer.get_by_text(text, exact=True).first
            try:
                cand.scroll_into_view_if_needed(timeout=5000)
                page.wait_for_timeout(600)
                box = cand.bounding_box()
                cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                inner_h = page.evaluate("window.innerHeight")
                if cy < 0 or cy > inner_h:
                    raise Retryable(f"{text} center off-viewport ({cx:.0f},{cy:.0f}) vs h={inner_h}")
                hit = page.evaluate(
                    """([x, y]) => {
                        const e = document.elementFromPoint(x, y);
                        if (!e) return null;
                        return {
                            tag: e.tagName,
                            text: (e.innerText || '').trim().slice(0, 60),
                            href: e.getAttribute('href'),
                            cls: typeof e.className === 'string' ? e.className.slice(0, 60) : ''
                        };
                    }""",
                    [cx, cy],
                )
                if hit is None:
                    raise Retryable(f"elementFromPoint null at {text} center")
                url_before = page.url
                page.mouse.click(cx, cy)
                page.wait_for_timeout(1500)
                hit_is_link = hit.get("tag") == "A" and (hit.get("href") or "") == href
                navigated = page.url.rstrip("/").endswith(href.rstrip("/"))
                probes.append({
                    "text": text,
                    "href": href,
                    "link_center": [round(cx, 1), round(cy, 1)],
                    "element_from_point": hit,
                    "covered": not hit_is_link,
                    "navigated": navigated,
                    "url_after": page.url,
                })
            except Retryable:
                raise
            except Exception as exc:
                probes.append({"text": text, "href": href, "probe_error": f"{type(exc).__name__}: {exc}"})
        reproduced = bool(any(p.get("covered") or (p.get("probe_error") is None and not p.get("navigated")) for p in probes))
        observed = {"probes": probes, "reproduced_by": "footer tap(s) covered / failed to navigate" if reproduced else "all footer taps navigated cleanly"}
        return reproduced, observed
    finally:
        capture(page, issue["id"])
        close_page(page)


def _broken_nav_check(ctx, url: str, fid: str) -> tuple[bool, dict]:
    page, resp = open_page(ctx, url)
    try:
        status = resp.status if resp else None
        title = page.title()
        body = page.locator("body").inner_text(timeout=5000)[:400]
        reproduced = status == 404
        observed = {"http_status": status, "page_title": title, "body_sample": body}
        return reproduced, observed
    finally:
        capture(page, fid)
        close_page(page)


def check_d004(ctx, issue):
    return _broken_nav_check(ctx, "https://www.injector.world/guides/botox-vs-filler", issue["id"])


def check_d012(ctx, issue):
    return _broken_nav_check(ctx, "https://www.injector.world/services/dysport", issue["id"])


UNLABELED_JS = """
Array.from(document.querySelectorAll('input, select, textarea')).filter(el => {
    if (el.type === 'hidden') return false;
    const id = el.id;
    const labelled = (el.labels && el.labels.length > 0)
        || (id && !!document.querySelector('label[for=\"' + id + '\"]'))
        || el.getAttribute('aria-label')
        || el.getAttribute('aria-labelledby')
        || el.getAttribute('title');
    return !labelled;
}).map(el => ({
    tag: el.tagName,
    type: el.type,
    name: el.name,
    id: el.id,
    placeholder: el.getAttribute('placeholder')
}))
"""


def _unlabeled_controls(ctx, url: str, fid: str) -> tuple[bool, dict]:
    page, resp = open_page(ctx, url)
    try:
        status = resp.status if resp else None
        page.wait_for_timeout(1000)
        unlabeled = page.evaluate(UNLABELED_JS)
        reproduced = len(unlabeled) > 0
        observed = {
            "http_status": status,
            "unlabeled_control_count": len(unlabeled),
            "unlabeled_controls": unlabeled,
        }
        return reproduced, observed
    finally:
        capture(page, fid)
        close_page(page)


def check_d018(ctx, issue):
    return _unlabeled_controls(ctx, "https://www.injector.world/services", issue["id"])


def check_d022(ctx, issue):
    return _unlabeled_controls(ctx, "https://www.injector.world/how-we-verify", issue["id"])


def check_d023(ctx, issue):
    return _unlabeled_controls(ctx, "https://www.injector.world/editorial-standards", issue["id"])


def check_d035(ctx, issue):
    """D-035 LOW: duplicate newsletter signup on guide article pages."""
    page, resp = open_page(ctx, "https://www.injector.world/guides/what-is-kybella")
    try:
        status = resp.status if resp else None
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        caption_count = page.get_by_text(
            "You will receive a confirmation email. Unsubscribe anytime."
        ).count()
        email_inputs = page.locator("input[type='email'], input[name*='email'], input#nl-email").count()
        reproduced = caption_count >= 2
        observed = {
            "http_status": status,
            "newsletter_caption_occurrences": caption_count,
            "email_input_count": email_inputs,
        }
        return reproduced, observed
    finally:
        capture(page, issue["id"])
        close_page(page)


HANDLERS = {
    "mobile-t9-1785640579-51": check_m001,
    "mobile-t11-1785642385-2": check_m003,
    "mobile-t11-1785642385-3": check_m008,
    "desktop-20260801-180803-44": check_d001,
    "desktop-20260801-175103-17": check_d004,
    "desktop-20260801-175239-33": check_d012,
    "desktop-20260801-174829-4": check_d018,
    "desktop-20260801-174926-8": check_d022,
    "desktop-20260801-174940-9": check_d023,
    "desktop-t6-1785611129-1": check_d035,
}

REPORT_IDS = {
    "mobile-t9-1785640579-51": "M-001",
    "mobile-t11-1785642385-2": "M-003",
    "mobile-t11-1785642385-3": "M-008",
    "desktop-20260801-180803-44": "D-001",
    "desktop-20260801-175103-17": "D-004",
    "desktop-20260801-175239-33": "D-012",
    "desktop-20260801-174829-4": "D-018",
    "desktop-20260801-174926-8": "D-022",
    "desktop-20260801-174940-9": "D-023",
    "desktop-t6-1785611129-1": "D-035",
}

DEVICE_CONTEXT = {
    "mobile-t9-1785640579-51": MOBILE_DEVICE,
    "mobile-t11-1785642385-2": MOBILE_DEVICE,
    "mobile-t11-1785642385-3": MOBILE_DEVICE,
    "desktop-20260801-180803-44": "desktop",
    "desktop-20260801-175103-17": "desktop",
    "desktop-20260801-175239-33": "desktop",
    "desktop-20260801-174829-4": "desktop",
    "desktop-20260801-174926-8": "desktop",
    "desktop-20260801-174940-9": "desktop",
    "desktop-t6-1785611129-1": "desktop",
}


def main() -> int:
    sample = select_sample()
    findings = {f["id"]: f for f in json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))}

    REVERIFY_DIR.mkdir(parents=True, exist_ok=True)

    harness._preset(MOBILE_DEVICE)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_by_device = {}
        try:
            for f in sample:
                fid = f["id"]
                handler = HANDLERS[fid]
                device = DEVICE_CONTEXT[fid]
                if device not in ctx_by_device:
                    if device == "desktop":
                        ctx_by_device[device] = harness.desktop_context(browser)
                    else:
                        ctx_by_device[device] = harness.mobile_context(browser, device)
                ctx = ctx_by_device[device]
                url = f["url"] if isinstance(f["url"], str) else f["url"][0]
                print(f"[{fid}] re-checking {url} ({device}) ...", flush=True)
                t0 = time.time()
                reproduced = observed = None
                attempts = 0
                while attempts < 3:
                    attempts += 1
                    try:
                        reproduced, observed = handler(ctx, f)
                        break
                    except Retryable as exc:
                        print(f"    retry {attempts}/3 (retryable): {exc}", flush=True)
                        time.sleep(2)
                    except Exception as exc:
                        print(f"    retry {attempts}/3 (error): {type(exc).__name__}: {exc}", flush=True)
                        time.sleep(2)
                    finally:
                        for stray in list(ctx.pages):
                            try:
                                stray.close()
                            except Exception:
                                pass
                if reproduced is None:
                    reproduced, observed = False, {"handler_error": "gave up after 3 probe attempts"}
                elapsed = round(time.time() - t0, 1)

                shot_path = REVERIFY_DIR / f"{fid}.png"
                shot_exists = shot_path.exists()

                results.append({
                    "id": fid,
                    "report_id": REPORT_IDS[fid],
                    "title": f["title"],
                    "url": url,
                    "device": device,
                    "severity": f["severity"],
                    "reproduced": reproduced,
                    "evidence_screenshot": str(shot_path) if shot_exists else None,
                    "timestamp": _iso_now(),
                    "elapsed_s": elapsed,
                    "observed": observed,
                })
                print(f"    -> reproduced={reproduced} ({elapsed}s)", flush=True)
        finally:
            for c in ctx_by_device.values():
                try:
                    c.close()
                except Exception:
                    pass
            browser.close()

    n_reproduced = sum(1 for r in results if r["reproduced"])
    log = {
        "campaign": "injector.world QA",
        "task": "T16 20% live re-verification of reported issues",
        "selection": {
            "method": "stratified random sample (fixed seed); per-device: guarantee each severity bucket present in the combined reported set; mobile 3/9, desktop 7/35",
            "seed": SAMPLE_SEED,
            "total_reported_issues": 44,
            "mobile_reported": 9,
            "desktop_reported": 35,
            "sample_size": len(results),
            "sample_pct": round(100 * len(results) / 44, 1),
            "required_min_pct": 20,
            "required_min_issues": 5,
            "guarantees": [">=1 mobile", ">=1 desktop", ">=1 issue per severity bucket present in combined set (CRITICAL/HIGH/MEDIUM/LOW)"],
            "by_device": {"mobile": sum(1 for r in results if r["device"] != "desktop"), "desktop": sum(1 for r in results if r["device"] == "desktop")},
            "by_severity": {sev: sum(1 for r in results if r["severity"] == sev) for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
            "sampled_ids": [r["id"] for r in results],
        },
        "summary": {
            "n_checked": len(results),
            "n_reproduced": n_reproduced,
            "n_not_reproduced": len(results) - n_reproduced,
            "all_reproduced": n_reproduced == len(results),
            "checked_at": _iso_now(),
        },
        "issues": results,
    }
    LOG_PATH.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {LOG_PATH}")
    print(f"summary: {n_reproduced}/{len(results)} reproduced")
    return 0 if n_reproduced == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
