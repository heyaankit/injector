#!/usr/bin/env python3
"""Probe mobile nav structure on homepage for both mobile devices (T10)."""
from playwright.sync_api import sync_playwright

DEVICES = ["iPhone 13", "Pixel 7"]
URL = "https://www.injector.world/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for dev in DEVICES:
        device = dict(p.devices[dev])
        ctx = browser.new_context(**device, locale="en-US")
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        print(f"===== {dev} ({device['viewport']['width']}x{device['viewport']['height']}) =====")
        info = page.evaluate("""() => {
            const out = {};
            out.innerWidth = window.innerWidth;
            out.docScrollWidth = document.documentElement.scrollWidth;
            out.hScroll = document.documentElement.scrollWidth > window.innerWidth + 1;
            out.bodyScrollWidth = document.body.scrollWidth;
            // header candidates
            const header = document.querySelector('header');
            out.headerExists = !!header;
            if (header) {
                const r = header.getBoundingClientRect();
                out.header = {top:r.top, height:r.height, position:getComputedStyle(header).position};
                out.headerFixed = getComputedStyle(header).position === 'fixed' || getComputedStyle(header).position === 'sticky';
            }
            // hamburger candidates
            const cands = [];
            document.querySelectorAll('button, [role="button"], a').forEach((el, i) => {
                const aria = (el.getAttribute('aria-label')||'').toLowerCase();
                const cls = (el.getAttribute('class')||'').toLowerCase();
                const txt = (el.textContent||'').trim().toLowerCase();
                const rect = el.getBoundingClientRect();
                if (aria.includes('menu') || cls.includes('hamburger') || cls.includes('nav-toggle') ||
                    cls.includes('menu-toggle') || txt.includes('menu') || (rect.width>0 && rect.width<60 && rect.height>0 && rect.height<60 && (el.querySelector('svg')||el.querySelector('span')))) {
                    cands.push({tag:el.tagName, cls:(el.getAttribute('class')||''), aria:(el.getAttribute('aria-label')||''),
                        ariaExpanded:el.getAttribute('aria-expanded'), txt:txt.slice(0,20), x:Math.round(rect.x), y:Math.round(rect.y), w:Math.round(rect.width), h:Math.round(rect.height), visible:el.offsetParent!==null});
                }
            });
            out.hamburgerCandidates = cands;
            // all header visible buttons/links
            const hb = [];
            if (header) header.querySelectorAll('button, a').forEach((el, i) => {
                const rect = el.getBoundingClientRect();
                if (el.offsetParent!==null && rect.width>0) hb.push({tag:el.tagName, cls:(el.getAttribute('class')||'').slice(0,40), aria:(el.getAttribute('aria-label')||''), txt:(el.textContent||'').trim().slice(0,25), w:Math.round(rect.width), h:Math.round(rect.height)});
            });
            out.headerButtons = hb;
            // footer disclaimer dup count
            let footText = '';
            const footer = document.querySelector('footer');
            if (footer) footText = footer.innerText;
            out.footerHasDisclaimer = footText.includes('Information here is editorial');
            out.disclaimerCount = (footText.match(/Information here is editorial and not medical advice\./g)||[]).length;
            // social anchors in footer
            out.socialAnchors = [];
            if (footer) footer.querySelectorAll('a').forEach((a) => {
                const lbl = (a.getAttribute('aria-label')||'').toLowerCase();
                if (lbl.includes('instagram') || lbl.includes('tiktok') || lbl.includes('facebook') || lbl.includes('twitter') || lbl.includes('youtube')) {
                    out.socialAnchors.push({aria:lbl, hasSvg:!!a.querySelector('svg'), href:(a.getAttribute('href')||'').slice(0,60), w:Math.round(a.getBoundingClientRect().width), h:Math.round(a.getBoundingClientRect().height)});
                }
            });
            // stats text
            const body = document.body.innerText;
            out.hasLiveStats = body.includes('LIVE') || body.includes('17,020') || body.includes('0+');
            out.statsMatches = (body.match(/\\d[\\d,]*\\+\\s*(clinic|brand|market|guide|metro|injector)?/gi)||[]).slice(0,12);
            return out;
        }""")
        import json
        print(json.dumps(info, indent=1))
        page.close(); ctx.close()
    browser.close()
