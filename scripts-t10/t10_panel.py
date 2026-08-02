#!/usr/bin/env python3
import json, time
from playwright.sync_api import sync_playwright


def goto(page, url, tries=3):
    for i in range(tries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(1200)
            return True
        except Exception as e:
            print(f"  retry {i+1}: {str(e)[:80]}")
            time.sleep(3)
    return False


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    for dev in ["iPhone 13", "Pixel 7"]:
        ctx = b.new_context(**dict(p.devices[dev]), locale="en-US")
        page = ctx.new_page()
        if not goto(page, "https://www.injector.world/"):
            print(dev, "FAILED")
            continue
        page.locator('button[aria-label*="menu" i]').first.click()
        page.wait_for_timeout(1000)
        r = page.evaluate("""() => {
            const nav = document.querySelector('header nav');
            const kids = nav ? [...nav.children] : [];
            const panelEl = kids.find(k => k.getBoundingClientRect().y > 60) || kids[kids.length-1];
            if (!panelEl) return {err:'no panel'};
            const pr = panelEl.getBoundingClientRect();
            const links = [...panelEl.querySelectorAll('a')].filter(a=>a.offsetParent!==null);
            const all = links.map(a => { const rr=a.getBoundingClientRect(); const cs=getComputedStyle(a);
                return {txt:(a.textContent||'').trim().slice(0,28), h:Math.round(rr.height), w:Math.round(rr.width),
                        py:parseFloat(cs.paddingTop)||0, pb:parseFloat(cs.paddingBottom)||0};
            });
            const sub44 = all.filter(x => x.h < 44);
            const dist = {};
            all.forEach(x => { dist[x.h] = (dist[x.h]||0)+1; });
            return {panel: {x:Math.round(pr.x), y:Math.round(pr.y), w:Math.round(pr.width), h:Math.round(pr.height),
                            bottom:Math.round(pr.bottom), innerH: window.innerHeight,
                            scrollH: panelEl.scrollHeight, clientH: panelEl.clientHeight,
                            scrollable: panelEl.scrollHeight > panelEl.clientHeight + 1},
                    linkCount: links.length, sub44Count: sub44.length,
                    heightDist: Object.entries(dist).map(([h,c])=>h+'px:'+c),
                    sub44Sample: sub44.slice(0,12)};
        }""")
        print(f"===== {dev} =====")
        print(json.dumps(r, indent=1))
        ctx.close()
    b.close()
