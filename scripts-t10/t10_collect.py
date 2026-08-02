#!/usr/bin/env python3
"""T10 mobile visual QA collection. Writes structured results to /tmp/t10_results.json."""
import json, time, sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

BASE = "https://www.injector.world/"
CLINIC_URLS = [
    "https://www.injector.world/clinics/utah/syracuse-ut/sinful-skin-injections-84075",
    "https://www.injector.world/clinics/missouri/lees-summit-mo/summit-aesthetics-64064",
]
PAGES = [BASE, BASE + "clinics"] + CLINIC_URLS
DEVICES = [("iPhone 13", "iphone-13"), ("Pixel 7", "pixel-7")]
OUT = {"results": {}, "evidence": {}}


def ts():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def evaluate(page, script):
    return page.evaluate(script)


def goto(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


OVERFLOW_JS = """() => {
    const iw = window.innerWidth;
    const sw = document.documentElement.scrollWidth;
    const offenders = [];
    if (sw > iw + 1) {
        document.querySelectorAll('body *').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;
            const cs = getComputedStyle(el);
            if (cs.position === 'fixed' && cs.visibility === 'hidden') return;
            if (r.right > iw + 1 && el.offsetParent !== null) {
                const t = (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 60);
                offenders.push({tag: el.tagName, cls: (el.getAttribute('class')||'').slice(0,60),
                    txt: t, right: Math.round(r.right), x: Math.round(r.x), w: Math.round(r.width)});
            }
        });
        offenders.sort((a,b) => b.right - a.right);
    }
    return {innerWidth: iw, scrollWidth: sw, overflow: sw > iw + 1, offenders: offenders.slice(0, 12)};
}"""


def check_hamburger(page, dev, dev_slug, shots):
    res = {"found": False}
    cand = evaluate(page, """() => {
        const btns = [...document.querySelectorAll('button, [role="button"]')];
        const b = btns.find(el => (el.getAttribute('aria-label')||'').toLowerCase().includes('menu') && el.offsetParent !== null);
        if (!b) return null;
        const r = b.getBoundingClientRect();
        return {cls: (b.getAttribute('class')||''), ariaExpanded: b.getAttribute('aria-expanded'),
                x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
    }""")
    if not cand:
        res["found"] = False
        return res
    res.update(found=True, toggle=cand)
    before = evaluate(page, """() => {
        const vis = [];
        document.querySelectorAll('[class*="menu"],[class*="drawer"],[class*="overlay"],[class*="sidebar"],[class*="nav"],[role="dialog"]').forEach(el => {
            if (el.offsetParent !== null) {
                const r = el.getBoundingClientRect();
                vis.push({tag:el.tagName, cls:(el.getAttribute('class')||'').slice(0,50), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
            }
        });
        return vis;
    }""")
    page.locator('button[aria-label*="menu" i]').first.click()
    page.wait_for_timeout(700)
    after = evaluate(page, """() => {
        const vis = [];
        document.querySelectorAll('[class*="menu"],[class*="drawer"],[class*="overlay"],[class*="sidebar"],[class*="nav"],[role="dialog"]').forEach(el => {
            if (el.offsetParent !== null) {
                const r = el.getBoundingClientRect();
                vis.push({tag:el.tagName, cls:(el.getAttribute('class')||'').slice(0,50), x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
            }
        });
        return vis;
    }""")
    new_vis = [v for v in after if v not in before]
    res["open_new_visible"] = new_vis
    res["aria_expanded_open"] = evaluate(page, 'document.querySelector(\'button[aria-label*="menu" i]\')?.getAttribute("aria-expanded")')
    res["overflow_open"] = evaluate(page, OVERFLOW_JS)
    # tap-target spacing: visible menu links min height
    res["menu_links"] = evaluate(page, """() => {
        const els = [];
        document.querySelectorAll('a,button').forEach(el => {
            const r = el.getBoundingClientRect();
            if (el.offsetParent !== null && r.width > 0 && r.height > 0 && r.height < 44 && r.top > 50) {
                els.push({tag:el.tagName, txt:(el.textContent||'').trim().slice(0,30), cls:(el.getAttribute('class')||'').slice(0,50), h:Math.round(r.height), w:Math.round(r.width)});
            }
        });
        return els.slice(0,20);
    }""")
    pname = "home"
    shot_dir = f"evidence/{dev_slug}/{pname}"
    import pathlib
    pathlib.Path(shot_dir).mkdir(parents=True, exist_ok=True)
    open_path = f"{shot_dir}/{ts()}-hamburger-open.png"
    page.screenshot(path=open_path)
    res["screenshot_open"] = open_path
    shots.append(open_path)
    # try close via toggle again
    page.locator('button[aria-label*="menu" i]').first.click()
    page.wait_for_timeout(600)
    res["aria_expanded_closed"] = evaluate(page, 'document.querySelector(\'button[aria-label*="menu" i]\')?.getAttribute("aria-expanded")')
    res["menu_visible_after_close"] = evaluate(page, """() => {
        return [...document.querySelectorAll('[class*="drawer"],[class*="mobile-menu"],[role="dialog"]')].some(el => el.offsetParent !== null && el.getBoundingClientRect().width > 100);
    }""")
    closed_path = f"{shot_dir}/{ts()}-hamburger-closed.png"
    page.screenshot(path=closed_path)
    res["screenshot_closed"] = closed_path
    shots.append(closed_path)
    res["overflow_closed"] = evaluate(page, OVERFLOW_JS)
    return res


def check_page(page, url, dev, dev_slug, shots):
    goto(page, url)
    ov = evaluate(page, OVERFLOW_JS)
    out = {"url": url, "overflow": ov}
    if ov["overflow"]:
        shot_dir = f"evidence/{dev_slug}/{url.rstrip('/').split('/')[-1] or 'home'}"
        import pathlib
        pathlib.Path(shot_dir).mkdir(parents=True, exist_ok=True)
        p = f"{shot_dir}/{ts()}-overflow.png"
        page.screenshot(path=p)
        out["overflow_shot"] = p
        shots.append(p)
    # sticky header
    vh = evaluate(page, "window.innerHeight")
    page.evaluate(f"window.scrollTo(0, {int(vh*2)})")
    page.wait_for_timeout(500)
    out["header_after_scroll"] = evaluate(page, """() => {
        const h = document.querySelector('header');
        if (!h) return null;
        const r = h.getBoundingClientRect();
        const cs = getComputedStyle(h);
        return {pos: cs.position, top: Math.round(r.top), h: Math.round(r.height),
                bg: cs.backgroundColor, backdrop: cs.backdropFilter,
                hasLinkAtTop: !!h.querySelector('a,button')};
    }""")
    # content under header? sample elementFromPoint at header text location
    out["header_overlap_sample"] = evaluate(page, """() => {
        const h = document.querySelector('header');
        if (!h) return null;
        const r = h.getBoundingClientRect();
        const y = Math.round(r.bottom - 12);
        const x = Math.round(r.left + r.width/2);
        const el = document.elementFromPoint(x, y);
        const hd = document.elementFromPoint(Math.round(r.left+30), Math.round(r.top+20));
        return {mid: el ? (el.tagName + '.' + (el.getAttribute('class')||'').slice(0,40)) : null,
                topLeft: hd ? hd.tagName : null};
    }""")
    page.evaluate("window.scrollTo(0,0)")
    page.wait_for_timeout(300)
    return out


def check_home_suspects(page, dev, dev_slug, shots):
    res = evaluate(page, """() => {
        const foot = document.querySelector('footer');
        let ft = foot ? foot.innerText : '';
        const visibleDisc = [];
        if (foot) foot.querySelectorAll('*').forEach(el => {
            if (el.offsetParent !== null && el.innerText && el.innerText.trim() === 'Information here is editorial and not medical advice.' && !el.children.length) {
                visibleDisc.push(el.tagName);
            }
        });
        const social = [];
        if (foot) foot.querySelectorAll('a').forEach(a => {
            const lbl = (a.getAttribute('aria-label')||'');
            if (/instagram|tiktok|facebook|twitter|youtube/i.test(lbl)) {
                const r = a.getBoundingClientRect();
                social.push({aria: lbl, hasSvg: !!a.querySelector('svg'), w: Math.round(r.width), h: Math.round(r.height), txt: (a.textContent||'').trim().slice(0,10)});
            }
        });
        const imgs = [];
        document.querySelectorAll('img').forEach(im => {
            if (!im.offsetParent) return;
            const r = im.getBoundingClientRect();
            const nw = im.naturalWidth, nh = im.naturalHeight;
            if (nw > 0 && nh > 0 && r.width > 0 && r.height > 0) {
                const renderAR = r.width / r.height, natAR = nw / nh;
                if (Math.abs(renderAR - natAR) / natAR > 0.35) {
                    imgs.push({src:(im.getAttribute('src')||'').slice(0,70), natAR:+(natAR.toFixed(2)), renderAR:+(renderAR.toFixed(2))});
                }
            }
        });
        return {disclaimerVisible: visibleDisc, disclaimerTextCount: (ft.match(/Information here is editorial and not medical advice\./g)||[]).length,
                social, distortedImgs: imgs.slice(0,8)};
    }""")
    # stats count-up check
    vh = evaluate(page, "window.innerHeight")
    page.evaluate(f"window.scrollTo(0, {int(vh*2.5)})")
    page.wait_for_timeout(2500)
    res["stats_after_scroll"] = evaluate(page, """() => {
        const body = document.body.innerText;
        const m = body.match(/\\d[\\d,]*\\+\\s*(clinics?|brands?|markets?|guides?|metro areas?|injectors?)/gi) || [];
        return m.slice(0, 10);
    }""")
    page.evaluate("window.scrollTo(0,0)")
    return res


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for dev, dev_slug in DEVICES:
        d = dict(p.devices[dev])
        ctx = browser.new_context(**d, locale="en-US")
        page = ctx.new_page()
        dres = {"viewport": d["viewport"], "pages": []}
        shots = []
        goto(page, BASE)
        dres["hamburger"] = check_hamburger(page, dev, dev_slug, shots)
        dres["home_suspects"] = check_home_suspects(page, dev, dev_slug, shots)
        for u in PAGES:
            dres["pages"].append(check_page(page, u, dev, dev_slug, shots))
        ctx.close()
        OUT["results"][dev_slug] = dres
        OUT["evidence"][dev_slug] = shots
    browser.close()

with open("/tmp/t10_results.json", "w") as f:
    json.dump(OUT, f, indent=1)
print("DONE results written")
for k, v in OUT["results"].items():
    print(f"=== {k} ===")
    h = v["hamburger"]
    print("hamburger found:", h.get("found"), "| toggle:", h.get("toggle"))
    print("  aria open/closed:", h.get("aria_expanded_open"), "/", h.get("aria_expanded_closed"))
    print("  menu_visible_after_close:", h.get("menu_visible_after_close"))
    print("  overflow when open:", h.get("overflow_open", {}).get("overflow"))
    print("  menu_links <44px h:", h.get("menu_links"))
    print("  shots:", h.get("screenshot_open"), h.get("screenshot_closed"))
    hs = v["home_suspects"]
    print("  disclaimer visible count:", hs.get("disclaimerTextCount"), "| social:", hs.get("social"))
    print("  distorted imgs:", hs.get("distortedImgs"))
    print("  stats:", hs.get("stats_after_scroll"))
    for pg in v["pages"]:
        o = pg["overflow"]
        tag = "OVERFLOW" if o["overflow"] else "ok"
        print(f"  [{tag}] {pg['url']}  sw={o['scrollWidth']} iw={o['innerWidth']}")
        if o["overflow"]:
            for off in o["offenders"][:5]:
                print("      offender:", off.get("tag"), off.get("txt"), "right=", off.get("right"))
        print("     header:", pg.get("header_after_scroll"))
