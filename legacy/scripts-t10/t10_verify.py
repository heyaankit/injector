#!/usr/bin/env python3
"""T10 verification: drawer link tap-targets, header bleed-through, overlap sampling."""
import json
from playwright.sync_api import sync_playwright

BASE = "https://www.injector.world/"


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for dev in ["iPhone 13", "Pixel 7"]:
        ctx = browser.new_context(**dict(p.devices[dev]), locale="en-US")
        page = ctx.new_page()
        goto(page, BASE)
        slug = dev.lower().replace(" ", "-")

        closed_links = page.evaluate("""() => {
            const small = [...document.querySelectorAll('a')].filter(a => {
                const r = a.getBoundingClientRect();
                return a.offsetParent !== null && r.width>0 && r.height>0 && r.height<44 && r.top>50;
            }).map(a => { const r=a.getBoundingClientRect(); const cs=getComputedStyle(a);
                return {txt:(a.textContent||'').trim().slice(0,25), h:Math.round(r.height), py:cs.paddingTop, pb:cs.paddingBottom}; });
            return small.slice(0,25);
        }""")

        page.locator('button[aria-label*="menu" i]').first.click()
        page.wait_for_timeout(700)
        open_links = page.evaluate("""() => {
            const small = [...document.querySelectorAll('a')].filter(a => {
                const r = a.getBoundingClientRect();
                return a.offsetParent !== null && r.width>0 && r.height>0 && r.height<44 && r.top>50;
            }).map(a => { const r=a.getBoundingClientRect(); const cs=getComputedStyle(a);
                return {txt:(a.textContent||'').trim().slice(0,25), h:Math.round(r.height), py:cs.paddingTop, pb:cs.paddingBottom}; });
            return {count: small.length, sample: small.slice(0,8)};
        }""")

        drawer_info = page.evaluate("""() => {
            const drawer = [...document.querySelectorAll('[class*="drawer"],[class*="sheet"],[class*="sidebar"],[class*="overlay"],[class*="mobile-menu"]')]
                .find(el => el.offsetParent !== null && el.getBoundingClientRect().width > 100);
            if (!drawer) return null;
            const r = drawer.getBoundingClientRect();
            const cs = getComputedStyle(drawer);
            const links = [...drawer.querySelectorAll('a')].filter(a=>a.offsetParent!==null);
            const sub44 = links.filter(a => { const rr=a.getBoundingClientRect(); return rr.height<44; }).length;
            return {cls:(drawer.getAttribute('class')||'').slice(0,60), x:Math.round(r.x), y:Math.round(r.y),
                    w:Math.round(r.width), h:Math.round(r.height), right:Math.round(r.right),
                    innerW: window.innerWidth, overflowX: drawer.scrollWidth > drawer.clientWidth + 1,
                    linkCount: links.length, sub44pxCount: sub44,
                    minH: Math.min(...links.map(a=>a.getBoundingClientRect().height)),
                    bg: cs.backgroundColor, pos: cs.position};
        }""")

        scrolled_shot = f"evidence/{slug}/home/{__import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y%m%d-%H%M%S')}-scrolled-header.png"
        page.evaluate(f"window.scrollTo(0, {int(page.evaluate('window.innerHeight')*2)})")
        page.wait_for_timeout(800)
        page.screenshot(path=scrolled_shot)

        page.evaluate("window.scrollTo(0,0)")
        page.wait_for_timeout(400)
        page.locator('body').press("Escape")
        page.wait_for_timeout(400)

        overlap = page.evaluate("""() => {
            const iw = window.innerWidth, vh = window.innerHeight;
            const hits = [];
            for (let y = 80; y < vh; y += 120) {
                for (let x = 40; x < iw; x += 100) {
                    const el = document.elementFromPoint(x, y);
                    if (!el) continue;
                    const r = el.getBoundingClientRect();
                    if (r.height === 0) continue;
                    const txt = (el.textContent||'').trim();
                    const clipped = el.scrollWidth > el.clientWidth + 2 && r.height > 10;
                    if ((txt && txt.length > 2) || clipped) {
                        hits.push({x, y, tag: el.tagName, cls:(el.getAttribute('class')||'').slice(0,40),
                            txt: txt.slice(0,30), scrollClip: clipped});
                    }
                }
            }
            return hits;
        }""")

        print(f"===== {dev} =====")
        print("closed <44px links:", len(closed_links), closed_links[:4])
        print("open <44px links:", open_links.get("count"), open_links.get("sample", [])[:3])
        print("drawer:", json.dumps(drawer_info, indent=1))
        print("scrolled shot:", scrolled_shot)
        print("overlap hits:", len(overlap), overlap[:6])
        ctx.close()
    browser.close()
