#!/usr/bin/env python3
"""T12 Mobile Responsive + A11y + Performance QA (injector.world).

Phases:
  A. Baseline: unthrottled homepage load (iPhone 13)
  B. Landscape responsive: homepage + /clinics on both devices (landscape viewport)
  C. Orientation: portrait->landscape reflow on homepage (both devices)
  D. Mobile a11y: unnamed interactive elements on homepage + /clinics + 1 guide (iPhone 13, confirm Pixel 7)
  E. Contrast: key text over images (computed color + PIL pixel sampling)
  F. Throttled perf: homepage + /clinics + guide + 1 clinic detail (Slow 4G + 4x CPU)

Output: data/t12-mobile-results.json  (appended evidence only; findings filed separately)
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from playwright.sync_api import sync_playwright
from harness import ROOT, DATA_DIR


def _mctx(browser, p, name):
    return browser.new_context(**dict(p.devices[name]), locale="en-US")

BASE = "https://www.injector.world"
EVID = ROOT / "evidence"
OUT = DATA_DIR / "t12-mobile-results.json"
GUIDE = BASE + "/guides/what-is-kybella"
CLINICS = BASE + "/clinics"
HOME = BASE + "/"

PORTRAIT = {"iphone-13": (390, 664), "pixel-7": (412, 839)}
LANDSCAPE = {"iphone-13": (844, 390), "pixel-7": (915, 412)}

THROTTLE = {
    "offline": False,
    "downloadThroughput": int(400 * 1000 / 8),  # 400 kbps -> bytes/s
    "uploadThroughput": int(75 * 1000 / 8),     # 75 kbps
    "latency": 400,
}

DESKTOP_THROTTLED = {HOME: 31779, CLINICS: 30161, GUIDE: 19326}


def rel_lum(c):
    c = [x / 255.0 for x in c]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(c1, c2):
    l1, l2 = rel_lum(c1), rel_lum(c2)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def hex2rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def wait_load_event(page, timeout=90000):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = page.evaluate("window.performance.timing.loadEventEnd")
        except Exception:
            v = 0
        if v and v > 0:
            return v
        time.sleep(0.25)
    return None


def resource_summary(page):
    return page.evaluate(
        """() => {
      const es = performance.getEntriesByType('resource');
      let total = 0, next = 0, imgN = 0, big = [];
      for (const e of es) {
        const s = e.transferSize || e.encodedBodySize || 0;
        total += s;
        if (/\\/_next\\/image/.test(e.name)) {
          imgN += s;
          big.push({n: e.name.slice(0, 120), s: s});
        }
      }
      big.sort((a, b) => b.s - a.s);
      return {total, count: es.length, nextImageBytes: imgN, top: big.slice(0, 4)};
    }"""
    )


def apply_throttle(page):
    sess = page.context.new_cdp_session(page)
    sess.send("Network.enable")
    sess.send("Network.emulateNetworkConditions", THROTTLE)
    sess.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    return sess


def main():
    results = {"baseline": {}, "landscape": [], "orientation": [], "a11y": [], "contrast": [], "perf": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # ---------- A. Baseline unthrottled homepage (iPhone 13) ----------
        try:
            ctx = _mctx(browser, p, "iPhone 13")
            page = ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            lee = wait_load_event(page, timeout=30000)
            page.wait_for_timeout(500)
            results["baseline"] = {
                "url": HOME,
                "loadEventEnd": lee,
                "weight": resource_summary(page),
            }
            EVID.joinpath("iphone-13", "perf").mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(EVID / "iphone-13" / "perf" / "t12-home-baseline.png"))
            ctx.close()
        except Exception as e:  # noqa: BLE001
            results["baseline"]["error"] = str(e)

        # ---------- B. Landscape responsive (both devices) ----------
        for dev, (w, h) in LANDSCAPE.items():
            for label, url in (("home", HOME), ("clinics", CLINICS)):
                rec = {"device": dev, "page": label, "url": url}
                try:
                    ctx = _mctx(browser, p, "iPhone 13" if dev == "iphone-13" else "Pixel 7")
                    page = ctx.new_page()
                    page.set_viewport_size({"width": w, "height": h})
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000)
                    dims = page.evaluate(
                        """() => ({sw: document.documentElement.scrollWidth,
                                   iw: window.innerWidth,
                                   sh: document.documentElement.scrollHeight,
                                   ih: window.innerHeight})"""
                    )
                    rec["scrollWidth"] = dims["sw"]
                    rec["innerWidth"] = dims["iw"]
                    rec["hOverflow"] = dims["sw"] > dims["iw"] + 1
                    ham = page.locator('button[aria-label="Open menu"]')
                    rec["hamCount"] = ham.count()
                    if ham.count():
                        rec["hamVisible"] = ham.first.is_visible()
                        try:
                            ham.first.click(timeout=3000)
                            page.wait_for_timeout(700)
                            rec["hamExpanded"] = ham.first.get_attribute("aria-expanded")
                            rec["menuOpen"] = page.evaluate(
                                """() => { const n = document.querySelector('header nav'); if(!n) return null;
                                    const cs = getComputedStyle(n); return cs.height; }"""
                            )
                        except Exception as e:  # noqa: BLE001
                            rec["hamClickError"] = str(e)
                    outdir = EVID / dev / "t12-landscape"
                    outdir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(outdir / f"{label}-landscape.png"))
                    ctx.close()
                except Exception as e:  # noqa: BLE001
                    rec["error"] = str(e)
                results["landscape"].append(rec)

        # ---------- C. Orientation portrait->landscape (both devices) ----------
        for dev in PORTRAIT:
            rec = {"device": dev, "url": HOME}
            try:
                ctx = _mctx(browser, p, "iPhone 13" if dev == "iphone-13" else "Pixel 7")
                page = ctx.new_page()
                page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                pw, ph = PORTRAIT[dev]
                page.set_viewport_size({"width": pw, "height": ph})
                page.wait_for_timeout(600)
                lw, lh = LANDSCAPE[dev]
                page.set_viewport_size({"width": lw, "height": lh})
                page.wait_for_timeout(1200)
                dims = page.evaluate(
                    """() => ({sw: document.documentElement.scrollWidth,
                               iw: window.innerWidth,
                               sh: document.documentElement.scrollHeight,
                               ih: window.innerHeight})"""
                )
                rec["hOverflow"] = dims["sw"] > dims["iw"] + 1
                rec["dims"] = dims
                # elementFromPoint grid overlap sampling (points over viewport)
                hits = page.evaluate(
                    """() => {
                      const pts = [];
                      for (let gx = 0; gx < 5; gx++)
                        for (let gy = 0; gy < 4; gy++) {
                          const x = Math.round(window.innerWidth * (gx + 0.5) / 5);
                          const y = Math.round(window.innerHeight * (gy + 0.5) / 4);
                          const el = document.elementFromPoint(x, y);
                          if (el) pts.push({x, y, tag: el.tagName,
                            cls: (el.className||'').toString().slice(0,40),
                            z: getComputedStyle(el).zIndex, pos: getComputedStyle(el).position,
                            txt: (el.textContent||'').slice(0,30)});
                        }
                      return pts;
                    }"""
                )
                rec["hits"] = hits
                outdir = EVID / dev / "t12-orientation"
                outdir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(outdir / "home-landscape-after-rotate.png"))
                ctx.close()
            except Exception as e:  # noqa: BLE001
                rec["error"] = str(e)
            results["orientation"].append(rec)

        # ---------- D. A11y unnamed interactive elements ----------
        A11Y_PAGES = [("home", HOME), ("clinics", CLINICS), ("guide", GUIDE)]
        A11Y_JS = """() => {
          const skip = /search/i;
          const named = (el) => {
            const g = (s) => { const v = el.getAttribute(s); return v && v.trim() ? v.trim() : null; };
            if (g('aria-label')) return true;
            const alb = g('aria-labelledby');
            if (alb) { for (const id of alb.split(/\\s+/)) { const r = document.getElementById(id); if (r && r.textContent.trim()) return true; } }
            if (g('title')) return true;
            if (el.tagName==='INPUT'||el.tagName==='SELECT'||el.tagName==='TEXTAREA') {
              if (el.id && document.querySelector('label[for="'+CSS.escape(el.id)+'"]')) return true;
              if (el.closest('label')) return true;
            }
            if ((el.innerText||'').trim()) return true;
            if (el.tagName==='INPUT' && ['submit','button','reset'].includes(el.type) && (el.value||'').trim()) return true;
            if (el.tagName==='A') {
              const img = el.querySelector('img');
              if (img && (img.alt||'').trim()) return true;
              const st = el.querySelector('svg title');
              if (st && st.textContent.trim()) return true;
            }
            return false;
          };
          const sel = 'button, a[href], input, select, textarea, [role="button"], [role="link"]';
          const out = [];
          for (const el of document.querySelectorAll(sel)) {
            if (el.closest('[aria-hidden="true"]')) continue;
            const cs = getComputedStyle(el);
            if (cs.display==='none'||cs.visibility==='hidden'||cs.opacity==='0') continue;
            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) continue;
            const ph = el.getAttribute('placeholder')||'';
            if (el.tagName==='INPUT' && skip.test(ph)) continue;
            if (!named(el)) out.push({tag: el.tagName,
              cls: (el.className||'').toString().slice(0,70),
              ph: ph.slice(0,30), text:(el.innerText||'').slice(0,40),
              x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)});
          }
          return out;
        }"""
        for dev in ("iphone-13", "pixel-7"):
            for label, url in A11Y_PAGES:
                rec = {"device": dev, "page": label, "url": url}
                try:
                    ctx = _mctx(browser, p, "iPhone 13" if dev == "iphone-13" else "Pixel 7")
                    page = ctx.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000)
                    rec["unnamed"] = page.evaluate(A11Y_JS)
                    # also run contrast sampling on homepage + guide (iphone only)
                    ctx.close()
                except Exception as e:  # noqa: BLE001
                    rec["error"] = str(e)
                results["a11y"].append(rec)

        # ---------- E. Contrast: key text over images (iPhone 13, PIL sampling) ----------
        try:
            ctx = _mctx(browser, p, "iPhone 13")
            page = ctx.new_page()
            dsf = page.evaluate("window.devicePixelRatio")
            for label, url in (("home", HOME), ("guide", GUIDE)):
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2000)
                cand = page.evaluate(
                    """() => {
                      const out = [];
                      const els = document.querySelectorAll('h1,h2,h3,[class*="hero"] p');
                      for (const el of els) {
                        const cs = getComputedStyle(el);
                        const r = el.getBoundingClientRect();
                        if (r.width < 40 || r.height < 10) continue;
                        if (r.top > window.innerHeight || r.bottom < 0) continue;
                        if (cs.color === 'rgb(0, 0, 0)') continue;
                        // background image on self or ancestors
                        let bgImg = 'none', bgCol = cs.backgroundColor;
                        let n = el;
                        while (n && n !== document.body) {
                          const c = getComputedStyle(n);
                          if (c.backgroundImage !== 'none') { bgImg = c.backgroundImage; bgCol = c.backgroundColor; break; }
                          n = n.parentElement;
                        }
                        if (bgImg === 'none') continue;
                        out.push({tag: el.tagName, text: (el.textContent||'').trim().slice(0,50),
                          color: cs.color, bgImg: bgImg.slice(0,50), bgCol,
                          x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                          fs: parseFloat(cs.fontSize)});
                      }
                      return out.slice(0, 8);
                    }"""
                )
                shot_path = EVID / "iphone-13" / "t12-contrast" / f"{label}.png"
                shot_path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(shot_path))
                from PIL import Image

                im = Image.open(shot_path).convert("RGB")
                for c in cand:
                    try:
                        x0, y0 = int(c["x"] * dsf), int(c["y"] * dsf)
                        x1, y1 = int((c["x"] + c["w"]) * dsf), int((c["y"] + c["h"]) * dsf)
                        crop = im.crop((max(x0, 0), max(y0, 0), min(x1, im.width), min(y1, im.height)))
                        small = crop.resize((24, 12))
                        colors = small.getcolors(24 * 12)
                        colors.sort(reverse=True)
                        bg = colors[0][1] if colors else (255, 255, 255)
                        txt = hex2rgb(c["color"])
                        ratio = contrast(txt, bg)
                        c["sampledBg"] = bg
                        c["contrast"] = round(ratio, 2)
                    except Exception as e:  # noqa: BLE001
                        c["sampleError"] = str(e)
                results["contrast"].append({"device": "iphone-13", "page": label, "url": url, "cands": cand})
            ctx.close()
        except Exception as e:  # noqa: BLE001
            results["contrast"].append({"error": str(e)})

        # ---------- F. Throttled perf (iPhone 13, Slow 4G + 4x CPU) ----------
        clinic_url = None
        try:
            ctx = _mctx(browser, p, "iPhone 13")
            page = ctx.new_page()
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            hrefs = page.eval_on_selector_all(
                "a[href]",
                "els => els.map(e => e.href).filter(h => /\\/clinics\\/[^/]+\\/[^/]+\\/[^/]+$/.test(h))",
            )
            if hrefs:
                clinic_url = hrefs[0]
            ctx.close()
        except Exception as e:  # noqa: BLE001
            results["perf"].append({"error": f"clinic scrape: {e}"})

        perf_pages = [(HOME, "home"), (CLINICS, "clinics"), (GUIDE, "guide")]
        if clinic_url:
            perf_pages.append((clinic_url, "clinic-detail"))
        for url, label in perf_pages:
            rec = {"device": "iphone-13", "page": label, "url": url}
            try:
                ctx = _mctx(browser, p, "iPhone 13")
                page = ctx.new_page()
                apply_throttle(page)
                t0 = time.time()
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                lee = wait_load_event(page, timeout=90000)
                wall = round(time.time() - t0, 1)
                rec["loadEventEnd"] = lee
                rec["wall_ms"] = int(wall * 1000)
                rec["weight"] = resource_summary(page)
                d = DESKTOP_THROTTLED.get(url)
                if d:
                    rec["desktop_load_ms"] = d
                    rec["ratio"] = round((lee or 0) / d, 2)
                EVID.joinpath("iphone-13", "perf").mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(EVID / "iphone-13" / "perf" / f"t12-{label}-throttled.png"))
                ctx.close()
            except Exception as e:  # noqa: BLE001
                rec["error"] = str(e)
            results["perf"].append(rec)

        browser.close()

    OUT.write_text(json.dumps(results, indent=2))
    print("WROTE", OUT)
    print(json.dumps(results, indent=1)[:3000])


if __name__ == "__main__":
    main()
