#!/usr/bin/env python3
"""T11 re-test (post-review): nav menu links, card/footer taps, back/forward.

Runs on iPhone 13 + Pixel 7. Records results to
data/t11-retest-results.json and captures evidence screenshots. Appends
NOTHING to findings.json — the caller decides keep/not_reproducible.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path("/home/heyatoy/Projects/testing")
EVID = ROOT / "evidence"
BASE = "https://www.injector.world"
TOGGLE_CSS = "header button[aria-label='Open menu'], header button[aria-label='Close menu']"
DEVICES = [("iPhone 13", "iphone-13"), ("Pixel 7", "pixel-7")]

BROKEN = {
    "/guides/botox", "/guides/botox-cost-2026", "/guides/botox-vs-filler",
    "/guides/first-time-botox", "/guides/how-to-choose-injector",
    "/guides/is-botox-safe", "/guides/masseter-botox",
    "/guides/md-vs-np-vs-rn", "/guides/red-flags",
    "/services/botox", "/services/dysport", "/services/sculptra",
}


def ts():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def shot(page, slug, scenario, name):
    d = EVID / slug / scenario
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-{ts()}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
    except Exception:
        return ""
    return str(p)


def nav(page, url):
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(1800)
    except Exception:
        pass


def norm(url):
    return (url or "").rstrip("/")


def panel_links(page):
    return page.evaluate("""() => {
        const h = document.querySelector('header');
        if (!h) return {panel: null, links: []};
        // the panel is the overflow-y-auto dropdown below the 74px header
        const panel = Array.from(h.querySelectorAll('div')).find(d => getComputedStyle(d).overflowY === 'auto');
        if (!panel) return {panel: null, links: []};
        const pr = panel.getBoundingClientRect();
        const links = Array.from(panel.querySelectorAll('a[href]')).filter(a => {
            const r = a.getBoundingClientRect();
            const cs = getComputedStyle(a);
            if (r.width <= 0 || r.height <= 0) return false;
            if (cs.display === 'none' || cs.visibility === 'hidden') return false;
            return r.bottom > 0 && r.top < window.innerHeight;
        }).map(a => {
            const r = a.getBoundingClientRect();
            return {text: (a.innerText||'').trim().replace(/\\s+/g,' ').slice(0,35),
                    href: a.href,
                    top: Math.round(r.top), bottom: Math.round(r.bottom),
                    centerY: Math.round(r.top + r.height/2)};
        });
        return {panel: {top: Math.round(pr.top), bottom: Math.round(pr.bottom)}, links};
    }""")


def at_center(page, href):
    return page.evaluate("""(href) => {
        const a = Array.from(document.querySelectorAll('a[href]')).find(x => x.href === href);
        if (!a) return null;
        const r = a.getBoundingClientRect();
        const cx = r.left + r.width/2, cy = r.top + r.height/2;
        const el = document.elementFromPoint(cx, cy);
        return {x: Math.round(cx), y: Math.round(cy),
                coveredBy: (el && el !== a && !a.contains(el)) ? {
                    tag: el.tagName, text: (el.innerText||'').trim().slice(0,22),
                    href: el.href || null, cls: (el.className||'').toString().slice(0,50)
                } : null};
    }""", href)


def tap_link(page, href):
    page.evaluate("""(href) => {
        const a = Array.from(document.querySelectorAll('a[href]')).find(x => x.href === href);
        if (a) a.scrollIntoView({block: 'center'});
    }""", href)
    page.wait_for_timeout(600)
    pt = page.evaluate("""(href) => {
        const a = Array.from(document.querySelectorAll('a[href]')).find(x => x.href === href);
        if (!a) return null;
        const r = a.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return null;
        if (r.top < 0 || r.bottom > window.innerHeight) return null;
        return {x: r.left + r.width/2, y: r.top + r.height/2};
    }""", href)
    if not pt:
        return None
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(3500)
    return page.url


def toggle_open(page):
    t = page.locator(TOGGLE_CSS).first
    if not t.count():
        return False
    t.click()
    page.wait_for_timeout(1800)
    return True


def toggle_expanded(page):
    return page.evaluate("""() => {
        const b = document.querySelector("%s");
        return b ? b.getAttribute('aria-expanded') : null;
    }""" % TOGGLE_CSS)


def run_device(p, browser, device, slug):
    ctx = browser.new_context(**dict(p.devices[device]), locale="en-US")
    page = ctx.new_page()
    R = {"device": device, "slug": slug, "shots": {}}

    # ---------- NAV ----------
    nav(page, BASE)
    toggle_open(page)
    pl = panel_links(page)
    R["nav_panel"] = pl
    nav_results = []
    # candidate 1: a link in the AI-form band (top panel links, y ~200-300)
    # candidate 2: a link clearly below the band
    cand1 = cand2 = None
    for l in pl["links"]:
        p_ = norm(l["href"]).replace(BASE, "")
        if p_ in ("", "/", "/login") or p_ in BROKEN:
            continue
        if not cand1 and l["centerY"] < 300:
            cand1 = l
        elif not cand2 and l["centerY"] >= 300:
            cand2 = l
        if cand1 and cand2:
            break
    for label, cand in (("upper-band", cand1), ("lower", cand2)):
        if not cand:
            continue
        cov = at_center(page, cand["href"])
        result = tap_link(page, cand["href"])
        exp_after = toggle_expanded(page)
        ok = result is not None and norm(result) == norm(cand["href"])
        nav_results.append({"label": label, "text": cand["text"], "href": cand["href"],
                            "centerY": cand["centerY"], "coveredBy": cov and cov["coveredBy"],
                            "result_url": result, "navigated": ok,
                            "menu_closed": exp_after == "false"})
        R["shots"][f"nav-{label}"] = shot(page, slug, "t11-retest-nav", f"after-{label}")
        # back to home + reopen menu for next candidate
        if label == "upper-band":
            nav(page, BASE)
            toggle_open(page)
    R["nav"] = nav_results

    # ---------- TOUCH: clinic cards ----------
    nav(page, BASE)
    clinic_links = page.evaluate("""() => {
        const seen = new Set();
        return Array.from(document.querySelectorAll("a[href*='/clinics/']")).map(a => a.href)
            .filter(h => { if (seen.has(h)) return false; seen.add(h); return true; });
    }""")
    touch = []
    for href in clinic_links[:3]:
        cov = at_center(page, href)
        result = tap_link(page, href)
        ok = result is not None and norm(result).startswith(BASE + "/clinics")
        touch.append({"type": "clinic", "href": href, "coveredBy": cov and cov["coveredBy"],
                      "result_url": result, "navigated": ok})
        R["shots"][f"clinic-{href.split('/')[-1]}"] = shot(page, slug, "t11-retest-touch", f"clinic-{href.split('/')[-1]}")
        nav(page, BASE)
    # ---------- TOUCH: footer links ----------
    footer_links = page.evaluate("""() => {
        const f = document.querySelector('footer');
        if (!f) return [];
        return Array.from(f.querySelectorAll('a[href]')).map(a => ({
            text: (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 30),
            href: a.href
        })).filter(x => x.href.startsWith('%s'));
    }""" % BASE)
    seen, funiq = set(), []
    for l in footer_links:
        p_ = norm(l["href"]).replace(BASE, "")
        if l["href"] not in seen and p_ not in BROKEN and p_ and p_ not in ("", "/", "/login"):
            seen.add(l["href"])
            funiq.append(l)
    for l in funiq[:3]:
        cov = at_center(page, l["href"])
        result = tap_link(page, l["href"])
        ok = result is not None and result.startswith(BASE) and norm(result) != norm(BASE)
        touch.append({"type": "footer", "text": l["text"], "href": l["href"],
                      "coveredBy": cov and cov["coveredBy"], "result_url": result, "navigated": ok})
        R["shots"][f"footer-{l['text'][:12]}"] = shot(page, slug, "t11-retest-touch", f"footer-{l['text'][:12]}")
        nav(page, BASE)
    R["touch"] = touch

    # ---------- BACK / FORWARD ----------
    nav(page, BASE)
    bf = {}
    if clinic_links:
        bf["detail_href"] = clinic_links[0]
        result = tap_link(page, clinic_links[0])
        bf["detail_url"] = result
        if result and norm(result).startswith(BASE + "/clinics"):
            page.go_back()
            page.wait_for_timeout(3500)
            bf["back_url"] = page.url
            bf["back_hero"] = page.get_by_text("Find Your Injector.", exact=False).count() > 0
            bf["back_ok"] = norm(page.url) == norm(BASE) and bf["back_hero"]
            R["shots"]["back"] = shot(page, slug, "t11-retest-back", "after-back")
    R["backfwd"] = bf

    ctx.close()
    return R


def main():
    results = {}
    with sync_playwright() as p:
        for device, slug in DEVICES:
            print(f"\n########## {device} ##########")
            browser = p.chromium.launch(headless=True)
            try:
                results[device] = run_device(p, browser, device, slug)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    out = ROOT / "data" / "t11-retest-results.json"
    out.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nresults written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
