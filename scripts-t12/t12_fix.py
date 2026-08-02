#!/usr/bin/env python3
"""T12 fix pass: correct perf timing, landscape hamburger probe, contrast over <img>."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path("/home/heyatoy/Projects/testing")
DATA = ROOT / "data"
EVID = ROOT / "evidence"
BASE = "https://www.injector.world"
HOME = BASE + "/"
CLINICS = BASE + "/clinics"
GUIDE = BASE + "/guides/what-is-kybella"
THROTTLE = {"offline": False, "downloadThroughput": 50000, "uploadThroughput": 9375, "latency": 400}
DESK = {HOME: 31779, CLINICS: 30161, GUIDE: 19326}


def mctx(browser, p, name):
    return browser.new_context(**dict(p.devices[name]), locale="en-US")


def wait_load(page, timeout=90000):
    t0 = time.time()
    nav = page.evaluate("window.performance.timing.navigationStart")
    while time.time() - t0 < timeout:
        v = page.evaluate("window.performance.timing.loadEventEnd")
        if v and v > 0:
            return v - nav
        time.sleep(0.25)
    return None


def wsum(page):
    return page.evaluate(
        """() => {
      let total=0,next=0; const big=[];
      for (const e of performance.getEntriesByType('resource')) {
        const s=e.transferSize||e.encodedBodySize||0; total+=s;
        if (/\\/_next\\/image/.test(e.name)) { next+=s; big.push({n:e.name.slice(0,110),s}); }
      }
      big.sort((a,b)=>b.s-a.s);
      return {total, count: performance.getEntriesByType('resource').length, next, top: big.slice(0,3)};
    }"""
    )


def main():
    out = {"perf": [], "landscape_ham": [], "contrast": []}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)

        # landscape hamburger probe
        for dev, (w, h) in (("iphone-13", (844, 390)), ("pixel-7", (915, 412))):
            rec = {"device": dev}
            ctx = mctx(b, p, "iPhone 13" if dev == "iphone-13" else "Pixel 7")
            page = ctx.new_page()
            page.set_viewport_size({"width": w, "height": h})
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            rec["before"] = page.evaluate(
                """() => { const b=document.querySelector('header button[aria-label="Open menu"], header button[aria-label="Close menu"]');
                const n=document.querySelector('header nav'); return {exp: b?b.getAttribute('aria-expanded'):null,
                navH: n?getComputedStyle(n).height:null, iw: window.innerWidth, sw: document.documentElement.scrollWidth}; }"""
            )
            try:
                page.locator('header button[aria-label="Open menu"], header button[aria-label="Close menu"]').first.click(timeout=4000)
                page.wait_for_timeout(1200)
            except Exception as e:
                rec["click_error"] = str(e)
            rec["after"] = page.evaluate(
                """() => { const b=document.querySelector('header button[aria-label="Open menu"], header button[aria-label="Close menu"]');
                const n=document.querySelector('header nav');
                const panel = n? Array.from(n.querySelectorAll('div')).find(d=>getComputedStyle(d).overflowY==='auto'||getComputedStyle(d).maxHeight!=='none') : null;
                return {exp: b?b.getAttribute('aria-expanded'):null,
                navH: n?getComputedStyle(n).height:null,
                panelH: panel?getComputedStyle(panel).height:null,
                panelOverflow: panel? getComputedStyle(panel).overflowY:null,
                iw: window.innerWidth, vh: window.innerHeight, sw: document.documentElement.scrollWidth,
                hOverflow: document.documentElement.scrollWidth > window.innerWidth+1}; }"""
            )
            EVID.joinpath(dev, "t12-landscape").mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(EVID / dev / "t12-landscape" / "home-hamburger-open.png"))
            ctx.close()
            out["landscape_ham"].append(rec)

        # contrast over <img> on guide + home
        for label, url in (("home", HOME), ("guide", GUIDE)):
            ctx = mctx(b, p, "iPhone 13")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            dsf = page.evaluate("window.devicePixelRatio")
            cand = page.evaluate(
                """() => {
                  const out=[];
                  for (const el of document.querySelectorAll('h1,h2,h3,p')) {
                    const r=el.getBoundingClientRect();
                    if (r.width<60||r.height<12) continue;
                    if (r.top>window.innerHeight||r.bottom<0) continue;
                    const cs=getComputedStyle(el);
                    const cx=r.left+r.width/2, cy=r.top+r.height/2;
                    const hit=document.elementFromPoint(cx,cy);
                    const overImg = hit && (hit.tagName==='IMG' || hit.closest('img') || /image/.test(getComputedStyle(hit).backgroundImage) || /image/.test(cs.backgroundImage));
                    if (!overImg) continue;
                    if (cs.color==='rgb(0, 0, 0)') continue;
                    out.push({tag:el.tagName, text:(el.textContent||'').trim().slice(0,60), color:cs.color,
                      x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height),
                      hitTag: hit?hit.tagName:null, hitCls:(hit?(hit.className||'').toString():'').slice(0,50)});
                  }
                  return out.slice(0,6);
                }"""
            )
            shot = EVID / "iphone-13" / "t12-contrast" / f"{label}.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot))
            from PIL import Image
            im = Image.open(shot).convert("RGB")

            def rel(c):
                c=[x/255 for x in c]; c=[x/12.92 if x<=0.03928 else ((x+0.055)/1.055)**2.4 for x in c]
                return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2]
            def cont(c1,c2):
                l1,l2=rel(c1),rel(c2)
                if l1<l2: l1,l2=l2,l1
                return (l1+0.05)/(l2+0.05)
            for c in cand:
                try:
                    x0,y0=int(c['x']*dsf),int(c['y']*dsf)
                    x1,y1=int((c['x']+c['w'])*dsf),int((c['y']+c['h'])*dsf)
                    crop=im.crop((max(x0,0),max(y0,0),min(x1,im.width),min(y1,im.height)))
                    small=crop.resize((24,12))
                    colors=small.getcolors(24*12); colors.sort(reverse=True)
                    bg=colors[0][1] if colors else (255,255,255)
                    txt=tuple(int(c['color'].split('(')[1].split(')')[0].split(',')[i].strip()) for i in range(3))
                    c['sampledBg']=bg; c['contrast']=round(cont(txt,bg),2)
                except Exception as e:
                    c['sampleError']=str(e)
            ctx.close()
            out["contrast"].append({"page": label, "url": url, "cands": cand})

        # perf re-measure with correct delta
        clinic = None
        ctx = mctx(b, p, "iPhone 13")
        page = ctx.new_page()
        page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e=>e.href).filter(h=>/\\/clinics\\/[^/]+\\/[^/]+\\/[^/]+$/.test(h))")
        if hrefs:
            clinic = hrefs[0]
        ctx.close()

        pages = [(HOME, "home"), (CLINICS, "clinics"), (GUIDE, "guide")]
        if clinic:
            pages.append((clinic, "clinic-detail"))
        for url, label in pages:
            rec = {"device": "iphone-13", "page": label, "url": url}
            try:
                ctx = mctx(b, p, "iPhone 13")
                page = ctx.new_page()
                sess = ctx.new_cdp_session(page)
                sess.send("Network.enable")
                sess.send("Network.emulateNetworkConditions", THROTTLE)
                sess.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                t0 = time.time()
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                delta = wait_load(page, timeout=90000)
                rec["load_ms"] = delta
                rec["wall_ms"] = int((time.time() - t0) * 1000)
                rec["weight"] = wsum(page)
                if url in DESK:
                    rec["desktop_ms"] = DESK[url]
                    rec["ratio"] = round(delta / DESK[url], 2)
                EVID.joinpath("iphone-13", "perf").mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(EVID / "iphone-13" / "perf" / f"t12-{label}-throttled.png"))
                ctx.close()
            except Exception as e:
                rec["error"] = str(e)
            out["perf"].append(rec)
        b.close()
    (DATA / "t12-fix-results.json").write_text(json.dumps(out, indent=2))
    print("WROTE t12-fix-results.json")


if __name__ == "__main__":
    main()
