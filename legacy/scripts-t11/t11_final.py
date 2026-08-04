#!/usr/bin/env python3
"""T11 final diagnostic: panel z-order + floating AI widget coverage."""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path("/home/heyatoy/Projects/testing")
EVID = ROOT / "evidence"
BASE = "https://www.injector.world"
TOGGLE_CSS = "header button[aria-label='Open menu'], header button[aria-label='Close menu']"


def run(p, browser, device, slug):
    ctx = browser.new_context(**dict(p.devices[device]), locale="en-US")
    page = ctx.new_page()
    R = {"device": device}
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    page.locator(TOGGLE_CSS).first.click()
    page.wait_for_timeout(1800)
    R["panel"] = page.evaluate("""() => {
        const h = document.querySelector('header');
        const panel = Array.from(h.querySelectorAll('div')).find(d => getComputedStyle(d).overflowY === 'auto');
        const chain = [];
        let anc = panel;
        while (anc && chain.length < 7) {
            const cs = getComputedStyle(anc);
            chain.push({tag: anc.tagName, cls: (anc.className||'').toString().slice(0,45),
                        pos: cs.position, z: cs.zIndex, blur: cs.backdropFilter.slice(0,20)});
            anc = anc.parentElement;
        }
        // Botox link at scrollY=0, no scroll
        const botox = Array.from(h.querySelectorAll('a[href]')).find(x => x.href === 'https://www.injector.world/brands/botox');
        const br = botox ? botox.getBoundingClientRect() : null;
        let botoxCov = null;
        if (br) {
            const el = document.elementFromPoint(br.left + br.width/2, br.top + br.height/2);
            botoxCov = {x: Math.round(br.left+br.width/2), y: Math.round(br.top+br.height/2),
                by: el && el !== botox ? {tag: el.tagName, text: (el.innerText||'').trim().slice(0,20),
                    cls: (el.className||'').toString().slice(0,50)} : null};
        }
        return {scrollY: window.scrollY, chain, botoxRect: br ? {top: Math.round(br.top), bottom: Math.round(br.bottom)} : null,
                botoxCovered: botoxCov};
    }""")
    pt = R["panel"].get("botoxCovered")
    if pt:
        page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(3500)
        R["botox_tap_result"] = page.url
        page.screenshot(path=str(EVID / slug / "t11-final" / f"botox-tap-{device.replace(' ','')}.png"), full_page=True)

    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1200)
    R["footer"] = page.evaluate("""() => {
        const out = {};
        // find fixed-position AI widget / any fixed element with Ask AI text
        const fixed = Array.from(document.querySelectorAll('*')).filter(el => {
            const cs = getComputedStyle(el);
            return cs.position === 'fixed' && el.getBoundingClientRect().width > 0;
        }).slice(0, 12).map(el => ({tag: el.tagName,
            cls: (el.className||'').toString().slice(0,60),
            text: (el.innerText||'').trim().slice(0,40),
            rect: (() => { const r = el.getBoundingClientRect(); return {top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height)}; })()}));
        out.fixedElements = fixed;
        // footer 'Cheek Filler' link coverage
        const f = document.querySelector('footer');
        const links = f ? Array.from(f.querySelectorAll('a[href]')).filter(a => /filler/i.test((a.innerText||''))) : [];
        out.footerFiller = links.slice(0,3).map(a => {
            const r = a.getBoundingClientRect();
            const el = r.width > 0 ? document.elementFromPoint(r.left + r.width/2, r.top + r.height/2) : null;
            return {text: (a.innerText||'').trim().slice(0,25),
                rect: {top: Math.round(r.top), bottom: Math.round(r.bottom)},
                coveredBy: el && el !== a ? {tag: el.tagName, text: (el.innerText||'').trim().slice(0,20),
                    cls: (el.className||'').toString().slice(0,50)} : null};
        });
        return out;
    }""")
    page.screenshot(path=str(EVID / slug / "t11-final" / f"footer-{device.replace(' ','')}.png"), full_page=True)
    ctx.close()
    return R


def main():
    out = {}
    with sync_playwright() as p:
        for device, slug in [("iPhone 13", "iphone-13"), ("Pixel 7", "pixel-7")]:
            browser = p.chromium.launch(headless=True)
            try:
                out[device] = run(p, browser, device, slug)
            finally:
                browser.close()
    pth = ROOT / "data" / "t11-final-diagnostic.json"
    pth.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
