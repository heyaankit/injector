#!/usr/bin/env python3
"""F3 - Evidence & Reproducibility Spot-Check (injector.world QA).

Independent 10-issue gate (seed 20260801, but a different stratification than
T16: 4 mobile / 6 desktop with both mobile HIGH issues included). Re-visits
each sampled issue's URL live in the recorded device context, re-asserts the
reported condition via DOM/HTTP assertions, captures fresh evidence under
evidence/f3/{id}.png, and validates that the recorded screenshot_path for
each finding exists on disk and is non-empty.

Design rules (per F3 spec):
  - Non-destructive: no form submits, no POSTs, no /admin/ or /api/.
  - Mobile via iPhone 13 preset, desktop 1920x1080 (harness helpers).
  - DOM assertions only; screenshots are evidence, never judged visually.
  - One page per check, sequential, polite delays, capped navigation.
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
F3_DIR = ROOT / "evidence" / "f3"
LOG_PATH = ROOT / "evidence" / "f3-log.json"

MOBILE_DEVICE = "iPhone 13"
NAV_TIMEOUT_MS = 30_000
NETWORKIDLE_CAP_MS = 10_000
SETTLE_MS = 1500

# id -> (report_id, assertion kind, [target urls])
SAMPLE = [
    ("mobile-t9-1785640579-51", "M-001", "m_home_claim", ["https://www.injector.world/"]),
    ("mobile-t9-1785640579-50", "M-002", "m_broken_links", [
        "https://www.injector.world/services/botox",
        "https://www.injector.world/guides/botox",
        "https://www.injector.world/services/dysport",
    ]),
    ("mobile-t11-1785642385-2", "M-003", "m_nav_overlap", ["https://www.injector.world"]),
    ("mobile-t9-1785640579-53", "M-005", "m_console_news", ["https://www.injector.world/news"]),
    ("desktop-20260801-180803-44", "D-001", "d_home_claim", ["https://www.injector.world"]),
    ("desktop-20260801-175115-19", "D-005", "broken_nav", ["https://www.injector.world/guides/first-time-botox"]),
    ("desktop-20260801-175023-12", "D-026", "unlabeled", ["https://www.injector.world/list-your-practice"]),
    ("desktop-20260801-174747-1", "D-015", "unlabeled", ["https://www.injector.world/"]),
    ("desktop-20260801-174815-3", "D-017", "unlabeled", ["https://www.injector.world/states"]),
    ("desktop-t6-1785611129-1", "D-035", "dup_newsletter", ["https://www.injector.world/guides/what-is-kybella"]),
]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_page(ctx, url: str):
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


def capture(page, fid: str) -> str | None:
    try:
        path = F3_DIR / f"{fid}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path) if path.exists() else None
    except Exception:
        return None


def scroll_collect(page, steps: int = 8, wait_ms: int = 1500) -> str:
    texts = []
    h = page.evaluate("document.body.scrollHeight")
    for i in range(steps + 1):
        page.evaluate(f"window.scrollTo(0, {int(h * i / steps)})")
        page.wait_for_timeout(wait_ms)
        texts.append(page.locator("body").inner_text(timeout=5000))
    return "\n".join(texts)


def check_m_home_claim(ctx, issue):
    page, resp = open_page(ctx, "https://www.injector.world/")
    try:
        status = resp.status if resp else None
        body = scroll_collect(page)
        has_17020 = "17,020" in body
        empty_state = "No verified clinics or injectors match." in body
        reproduced = bool(has_17020 and empty_state)
        return reproduced, {
            "http_status": status,
            "stats_band_17020_present": has_17020,
            "directory_empty_state_present": empty_state,
        }
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_m_broken_links(ctx, issue):
    urls = ["https://www.injector.world/services/botox",
            "https://www.injector.world/guides/botox",
            "https://www.injector.world/services/dysport"]
    results = []
    for u in urls:
        page, resp = open_page(ctx, u)
        try:
            status = resp.status if resp else None
            results.append({"url": u, "http_status": status})
            capture(page, f"{issue['id']}-{u.rstrip('/').split('/')[-1]}")
        finally:
            close_page(page)
    reproduced = all(r["http_status"] == 404 for r in results)
    return reproduced, {"probed_urls": results, "expected": "all 404"}


def _nav_menu_probe(page, hrefs) -> dict:
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
            probes.append({"href": href, "error": "no visible link"})
            continue
        box = target.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
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
        url_before = page.url
        page.mouse.click(cx, cy)
        page.wait_for_timeout(1500)
        hit_is_link = hit is not None and hit.get("tag") == "A" and (hit.get("href") or "") == href
        navigated = page.url.rstrip("/").endswith(href.rstrip("/"))
        probes.append({
            "href": href,
            "link_center": [round(cx, 1), round(cy, 1)],
            "element_from_point": hit,
            "covered": not hit_is_link,
            "navigated": navigated,
            "url_after": page.url,
        })
        if not navigated:
            page.goto("https://www.injector.world", wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            toggle = page.locator("button[aria-label='Open menu']").first
            toggle.click(timeout=8000)
            page.wait_for_timeout(1200)
    return {"probes": probes}


def check_m_nav_overlap(ctx, issue):
    page, resp = open_page(ctx, "https://www.injector.world")
    try:
        probe = _nav_menu_probe(page, ["/brands/botox", "/brands/sculptra"])
        probes = probe["probes"]
        reproduced = bool(any(p.get("covered") or not p.get("navigated") for p in probes))
        return reproduced, {"probes": probes}
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_m_console_news(ctx, issue):
    page, resp = open_page(ctx, "https://www.injector.world/news")
    console_errors = []
    failed = []

    def _on_console(msg):
        if msg.type == "error":
            console_errors.append(msg.text)

    def _on_requestfailed(req):
        failed.append({"url": req.url, "error": req.failure})

    try:
        page.on("console", _on_console)
        page.on("requestfailed", _on_requestfailed)
        page.reload(wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        status = resp.status if resp else None
        reproduced = len(console_errors) > 0
        return reproduced, {
            "http_status": status,
            "console_error_count": len(console_errors),
            "console_errors": console_errors[:10],
            "failed_requests": len(failed),
        }
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_d_home_claim(ctx, issue):
    page, resp = open_page(ctx, "https://www.injector.world")
    try:
        status = resp.status if resp else None
        body = scroll_collect(page, steps=10, wait_ms=1500)
        has_17020 = "17,020" in body
        has_12400 = "12,400" in body
        empty_state = "No verified clinics or injectors match." in body
        fixtures = [n for n in ["Test Clinic", "ABCD Clinic", "Rishav's Clinic"] if n in body]
        reproduced = bool(has_17020 and empty_state)
        return reproduced, {
            "http_status": status,
            "stats_band_17020_present": has_17020,
            "hero_12400_present": has_12400,
            "directory_empty_state_present": empty_state,
            "test_fixtures_found": fixtures,
        }
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_broken_nav(ctx, issue):
    url = issue["url"] if isinstance(issue["url"], str) else issue["url"][0]
    page, resp = open_page(ctx, url)
    try:
        status = resp.status if resp else None
        reproduced = status == 404
        return reproduced, {
            "http_status": status,
            "page_title": page.title(),
            "body_sample": page.locator("body").inner_text(timeout=5000)[:200],
        }
    finally:
        capture(page, issue["id"])
        close_page(page)


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


def check_unlabeled(ctx, issue):
    url = issue["url"] if isinstance(issue["url"], str) else issue["url"][0]
    page, resp = open_page(ctx, url)
    try:
        status = resp.status if resp else None
        page.wait_for_timeout(1000)
        unlabeled = page.evaluate(UNLABELED_JS)
        reproduced = len(unlabeled) > 0
        return reproduced, {
            "http_status": status,
            "unlabeled_control_count": len(unlabeled),
            "unlabeled_controls": unlabeled,
        }
    finally:
        capture(page, issue["id"])
        close_page(page)


def check_dup_newsletter(ctx, issue):
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
        return reproduced, {
            "http_status": status,
            "newsletter_caption_occurrences": caption_count,
            "email_input_count": email_inputs,
        }
    finally:
        capture(page, issue["id"])
        close_page(page)


HANDLERS = {
    "m_home_claim": check_m_home_claim,
    "m_broken_links": check_m_broken_links,
    "m_nav_overlap": check_m_nav_overlap,
    "m_console_news": check_m_console_news,
    "d_home_claim": check_d_home_claim,
    "broken_nav": check_broken_nav,
    "unlabeled": check_unlabeled,
    "dup_newsletter": check_dup_newsletter,
}

MOBILE_KINDS = {"m_home_claim", "m_broken_links", "m_nav_overlap", "m_console_news"}


def evidence_check(f: dict) -> dict:
    shot = f.get("screenshot_path") or ""
    paths = shot if isinstance(shot, list) else [shot]
    results = []
    for p in paths:
        full = ROOT / p if not Path(p).is_absolute() else Path(p)
        if not full.exists():
            results.append({"path": p, "exists": False, "size_bytes": None})
            continue
        size = full.stat().st_size
        results.append({
            "path": p,
            "exists": True,
            "size_bytes": size,
            "plausible": size > 1024,
            "note": None if size > 1024 else "size < 1KB - suspiciously small",
        })
    all_ok = bool(results) and all(r["exists"] and r["plausible"] for r in results)
    return {"paths_checked": results, "all_match": all_ok}


def main() -> int:
    findings = {f["id"]: f for f in json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))}
    F3_DIR.mkdir(parents=True, exist_ok=True)

    harness._preset(MOBILE_DEVICE)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_by_device = {}
        try:
            for fid, report_id, kind, urls in SAMPLE:
                f = findings[fid]
                device = MOBILE_DEVICE if kind in MOBILE_KINDS else "desktop"
                if device not in ctx_by_device:
                    if device == "desktop":
                        ctx_by_device[device] = harness.desktop_context(browser)
                    else:
                        ctx_by_device[device] = harness.mobile_context(browser, device)
                ctx = ctx_by_device[device]
                print(f"[{report_id}] {kind} -> {f['url']} ({device})", flush=True)
                t0 = time.time()
                handler = HANDLERS[kind]
                try:
                    reproduced, observed = handler(ctx, f)
                except Exception as exc:
                    reproduced, observed = False, {"handler_error": f"{type(exc).__name__}: {exc}"}
                finally:
                    for stray in list(ctx.pages):
                        try:
                            stray.close()
                        except Exception:
                            pass
                elapsed = round(time.time() - t0, 1)

                shot_path = F3_DIR / f"{fid}.png"
                shot_exists = shot_path.exists()

                ev = evidence_check(f)
                results.append({
                    "id": fid,
                    "report_id": report_id,
                    "title": f["title"],
                    "url": f["url"],
                    "device": device,
                    "severity": f["severity"],
                    "reproduced": reproduced,
                    "evidence_f3_screenshot": str(shot_path) if shot_exists else None,
                    "recorded_screenshot_check": ev,
                    "timestamp": _iso_now(),
                    "elapsed_s": elapsed,
                    "observed": observed,
                })
                print(f"    -> reproduced={reproduced} evidence_match={ev['all_match']} ({elapsed}s)", flush=True)
        finally:
            for c in ctx_by_device.values():
                try:
                    c.close()
                except Exception:
                    pass
            browser.close()

    n_reproduced = sum(1 for r in results if r["reproduced"])
    n_evmatch = sum(1 for r in results if r["recorded_screenshot_check"]["all_match"])
    log = {
        "campaign": "injector.world QA",
        "task": "F3 Evidence & Reproducibility Spot-Check (Final Verification Wave)",
        "selection": {
            "method": "stratified random sample (fixed seed 20260801); 4 mobile / 6 desktop; "
                      "force-include CRITICAL (1/device) + LOW (1 desktop); sample HIGH/MEDIUM per device",
            "seed": 20260801,
            "total_reported_issues": 43,
            "mobile_reported": 8,
            "desktop_reported": 35,
            "sample_size": len(results),
            "by_device": {"mobile": sum(1 for r in results if r["device"] != "desktop"),
                          "desktop": sum(1 for r in results if r["device"] == "desktop")},
            "by_severity": {sev: sum(1 for r in results if r["severity"] == sev)
                            for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
            "overlap_with_t16": [r["id"] for r in results
                                 if r["id"] in {"mobile-t9-1785640579-51", "mobile-t11-1785642385-2",
                                                "desktop-20260801-180803-44", "desktop-t6-1785611129-1"}],
            "sampled_ids": [r["id"] for r in results],
        },
        "summary": {
            "n_checked": len(results),
            "n_reproduced": n_reproduced,
            "n_not_reproduced": len(results) - n_reproduced,
            "evidence_n_match": n_evmatch,
            "evidence_n_checked": len(results),
            "all_reproduced": n_reproduced == len(results),
            "all_evidence_match": n_evmatch == len(results),
            "checked_at": _iso_now(),
        },
        "issues": results,
    }
    LOG_PATH.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    print(f"\nWROTE {LOG_PATH}")
    print(f"summary: {n_reproduced}/{len(results)} reproduced | "
          f"{n_evmatch}/{len(results)} evidence match")
    return 0 if n_reproduced == len(results) and n_evmatch == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
