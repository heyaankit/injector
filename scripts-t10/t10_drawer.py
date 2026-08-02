#!/usr/bin/env python3
"""Find what actually becomes visible when the mobile menu opens."""
import json
from playwright.sync_api import sync_playwright


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


VIS_JS = """() => {
    const vis = [];
    document.querySelectorAll('body *').forEach(el => {
        if (el.offsetParent === null) return;
        const r = el.getBoundingClientRect();
        if (r.width < 40 || r.height < 40) return;
        const cs = getComputedStyle(el);
        if (cs.position === 'absolute' && cs.visibility === 'hidden') return;
        vis.push(el.tagName + '|' + (el.getAttribute('class')||'').slice(0,55) + '|x' + Math.round(r.x) + 'y' + Math.round(r.y) + 'w' + Math.round(r.width));
    });
    return vis;
}"""


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for dev in ["iPhone 13", "Pixel 7"]:
        ctx = browser.new_context(**dict(p.devices[dev]), locale="en-US")
        page = ctx.new_page()
        goto(page, "https://www.injector.world/")
        before = set(page.evaluate(VIS_JS))
        toggle = page.locator('button[aria-label*="menu" i]').first
        parent_html = page.evaluate("""() => {
            const b = document.querySelector('button[aria-label*="menu" i]');
            let a = b;
            const chain = [];
            for (let i = 0; i < 4 && a; i++) { a = a.parentElement; if (a) chain.push(a.tagName + '.' + (a.getAttribute('class')||'').slice(0,60)); }
            return chain;
        }""")
        toggle.click()
        page.wait_for_timeout(800)
        after = set(page.evaluate(VIS_JS))
        new_el = sorted(after - before)
        exp = page.evaluate('document.querySelector(\'button[aria-label*="menu" i]\')?.getAttribute("aria-expanded")')
        body_scroll_lock = page.evaluate("getComputedStyle(document.body).overflow")
        overlay_info = page.evaluate("""() => {
            const fixedEls = [...document.querySelectorAll('body *')].filter(el => {
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return cs.position === 'fixed' && el.offsetParent !== null && r.width > 50;
            }).map(el => { const r = el.getBoundingClientRect(); return {tag: el.tagName, cls:(el.getAttribute('class')||'').slice(0,60), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height), right:Math.round(r.right)}; });
            return fixedEls;
        }""")
        print(f"===== {dev} =====")
        print("toggle chain:", parent_html)
        print("aria-expanded:", exp, "| body overflow:", body_scroll_lock)
        print("new visible elements:", len(new_el))
        for e in new_el[:25]:
            print("   +", e)
        print("fixed elements:", json.dumps(overlay_info, indent=0))
        # close via Escape
        page.locator('body').press("Escape")
        page.wait_for_timeout(600)
        exp2 = page.evaluate('document.querySelector(\'button[aria-label*="menu" i]\')?.getAttribute("aria-expanded")')
        after2 = set(page.evaluate(VIS_JS))
        print("after Escape aria-expanded:", exp2, "| new_el still visible:", len(after2 & new_el))
        ctx.close()
    browser.close()
