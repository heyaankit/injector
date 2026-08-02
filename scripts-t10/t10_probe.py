#!/usr/bin/env python3
"""T10 quick probe: nav structure + clinic links on both mobile devices."""
import json, sys
sys.path.insert(0, "scripts")
from playwright.sync_api import sync_playwright

DEVICES = ["iPhone 13", "Pixel 7"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for dev in DEVICES:
        ctx = browser.new_context(**dict(p.devices[dev]), locale="en-US")
        page = ctx.new_page()
        page.goto("https://www.injector.world/", wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        print(f"===== {dev} =====")
        info = page.evaluate("""() => {
            const out = {};
            out.innerWidth = window.innerWidth;
            out.docScrollWidth = document.documentElement.scrollWidth;
            // header
            const header = document.querySelector('header');
            if (header) {
                const r = header.getBoundingClientRect();
                out.header = {pos:getComputedStyle(header).position, top:r.top, h:r.height, bg:getComputedStyle(header).backgroundColor};
            }
            // hamburger candidates: visible interactive small elements in top bar
            const cands = [];
            document.querySelectorAll('button, [role="button"], a, [aria-haspopup], [aria-expanded]').forEach((el) => {
                const aria = (el.getAttribute('aria-label')||'').toLowerCase();
                const cls = (el.getAttribute('class')||'').toLowerCase();
                const rect = el.getBoundingClientRect();
                if (!el.offsetParent) return;
                if (aria.includes('menu') || cls.includes('hamburger') || cls.includes('nav-toggle') ||
                    cls.includes('menu-toggle') || cls.includes('mobile-menu') ||
                    (rect.width>0 && rect.width<70 && rect.height>0 && rect.height<70 &&
                     (el.querySelector('svg') || el.querySelector('span')) && rect.top < 120)) {
                    cands.push({tag:el.tagName, cls:(el.getAttribute('class')||''), aria:(el.getAttribute('aria-label')||''),
                        ariaExpanded:el.getAttribute('aria-expanded'), hasSvg:!!el.querySelector('svg'),
                        txt:(el.textContent||'').trim().slice(0,25), x:Math.round(rect.x), y:Math.round(rect.y),
                        w:Math.round(rect.width), h:Math.round(rect.height)});
                }
            });
            out.hamburgerCandidates = cands;
            // footer text checks
            const foot = document.querySelector('footer');
            let ft = '';
            if (foot) ft = foot.innerText;
            out.disclaimerCount = (ft.match(/Information here is editorial and not medical advice\./g)||[]).length;
            out.socialAnchors = [];
            if (foot) foot.querySelectorAll('a').forEach((a) => {
                const lbl = (a.getAttribute('aria-label')||'');
                if (/instagram|tiktok|facebook|twitter|youtube/i.test(lbl)) {
                    out.socialAnchors.push({aria:lbl, hasSvg:!!a.querySelector('svg'), svgSize: a.querySelector('svg') ? (a.querySelector('svg').getBoundingClientRect().width|0)+'x'+(a.querySelector('svg').getBoundingClientRect().height|0) : 'none'});
                }
            });
            return out;
        }""")
        print(json.dumps(info, indent=1))
        page.close(); ctx.close()
        # clinics page for links
        ctx2 = browser.new_context(**dict(p.devices[dev]), locale="en-US")
        page2 = ctx2.new_page()
        page2.goto("https://www.injector.world/clinics", wait_until="domcontentloaded", timeout=30000)
        try:
            page2.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page2.wait_for_timeout(1500)
        links = page2.evaluate("""() => {
            const out = [];
            document.querySelectorAll('main a, body a').forEach((a) => {
                const href = a.getAttribute('href')||'';
                if (!href.startsWith('http') && !href.startsWith('#')) return;
                const txt = (a.textContent||'').trim().slice(0,45);
                out.push({href:href.slice(0,90), txt, cls:(a.getAttribute('class')||'').slice(0,40)});
            });
            return out;
        }""")
        seen = set(); clinic_links = []
        for l in links:
            h = l['href']
            if h in seen: continue
            seen.add(h)
            clinic_links.append(l)
        # filter plausible clinic links
        plaus = [l for l in clinic_links if '/clinic' in l['href'].lower() or '/injector' in l['href'].lower() or '/pract' in l['href'].lower()]
        print(f"--- {dev} /clinics: total {len(clinic_links)} unique links, {len(plaus)} plausible clinic links")
        for l in (plaus[:12] if plaus else clinic_links[:12]):
            print("   ", l)
        print(f"--- {dev} scrollWidth: {page2.evaluate('document.documentElement.scrollWidth')} vs innerWidth {page2.evaluate('window.innerWidth')}")
        page2.close(); ctx2.close()
    browser.close()
