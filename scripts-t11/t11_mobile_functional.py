#!/usr/bin/env python3
"""T11: Mobile Functional QA (injector.world).

Per-device functional checks on iPhone 13 + Pixel 7:
  1. Site-wide search ("Botox" + valid location "Austin")
  2. Newsletter form validation (empty + not-an-email)
  3. Mobile nav (hamburger -> nav link -> navigation actually occurs, menu closes)
  4. Touch targets (2 clinic cards + 2 footer links tappable -> navigate)
  5. Back/forward (homepage -> clinic detail -> back restores homepage)
  6. Stats count-up (post-scroll final values rendered)
  7. Empty-state (no-results search renders a graceful message, no crash/blank)

Same defect on both devices is consolidated into ONE finding later
(device="iphone-13, pixel-7"). Appends findings to data/findings.json.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path("/home/heyatoy/Projects/testing")
EVID = ROOT / "evidence"
BASE = "https://www.injector.world"

NAV_TIMEOUT_MS = 30_000
NETWORKIDLE_CAP_MS = 10_000
SETTLE_MS = 1200

DEVICES = [("iPhone 13", "iphone-13"), ("Pixel 7", "pixel-7")]

# Known 404 link targets (T7/T9). Nav/touch tests must never pick these so we
# only surface NEW breakage.
BROKEN = {
    "/guides/botox", "/guides/botox-cost-2026", "/guides/botox-vs-filler",
    "/guides/first-time-botox", "/guides/how-to-choose-injector",
    "/guides/is-botox-safe", "/guides/masseter-botox",
    "/guides/md-vs-np-vs-rn", "/guides/red-flags",
    "/services/botox", "/services/dysport", "/services/sculptra",
}
PREFERRED = ["/about", "/states", "/clinics", "/how-we-verify", "/news",
             "/brands", "/contact", "/list-your-practice", "/services", "/guides"]

TOGGLE_CSS = "header button[aria-label='Open menu'], header button[aria-label='Close menu']"
VISIBLE_ANCHORS_JS = """() => {
    const h = document.querySelector('header');
    if (!h) return [];
    const vis = (el) => {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (r.width <= 0 || r.height <= 0) return false;
        if (cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') return false;
        return r.bottom > 0 && r.top < window.innerHeight &&
               r.right > 0 && r.left < window.innerWidth;
    };
    return Array.from(h.querySelectorAll('a[href]')).filter(vis).map(a => ({
        text: (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40),
        href: a.href
    }));
}"""


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def nav(page, url):
    try:
        resp = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    except Exception:
        return None
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
    except Exception:
        pass
    page.wait_for_timeout(SETTLE_MS)
    return resp.status if resp else None


def shot(page, slug, scenario, name):
    d = EVID / slug / scenario
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-{ts()}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
    except Exception:
        return ""
    return str(p)


def body_text(page) -> str:
    try:
        return page.locator("body").inner_text()
    except Exception:
        return ""


def norm_url(url: str) -> str:
    return url.rstrip("/") if url else url


def toggle_state(page):
    try:
        return page.evaluate("""() => {
            const b = document.querySelector("%s");
            return b ? b.getAttribute('aria-expanded') : null;
        }""" % TOGGLE_CSS)
    except Exception:
        return None


def click_visible_anchor(page, href, timeout_ms=8000):
    idx = page.evaluate("""(href) => {
        const h = document.querySelector('header');
        if (!h) return -1;
        const as = Array.from(h.querySelectorAll('a[href]'));
        for (let i = 0; i < as.length; i++) {
            const r = as[i].getBoundingClientRect();
            const cs = getComputedStyle(as[i]);
            if (as[i].href === href && r.width > 0 && r.height > 0 &&
                cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0' &&
                r.bottom > 0 && r.top < window.innerHeight &&
                r.right > 0 && r.left < window.innerWidth) return i;
        }
        return -1;
    }""", href)
    if idx < 0:
        return False
    page.locator(f"header a[href='{href}']").nth(idx).click(timeout=timeout_ms)
    return True


def mouse_tap(page, href):
    page.evaluate("""(href) => {
        const a = Array.from(document.querySelectorAll('a[href]')).find(x => x.href === href);
        if (a) a.scrollIntoView({block: 'center'});
    }""", href)
    page.wait_for_timeout(700)
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


def run_device(p, browser, device: str, slug: str) -> dict:
    ctx = browser.new_context(**dict(p.devices[device]), locale="en-US")
    page = ctx.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    R = {"device": device, "slug": slug, "shots": {}, "log": []}

    def log(msg):
        R["log"].append(msg)
        print(f"  [{device}] {msg}")

    def safe(phase_name, fn):
        try:
            fn()
        except Exception as exc:
            R[phase_name] = dict(R.get(phase_name) or {})
            R[phase_name]["phase_error"] = str(exc)[:200]
            log(f"{phase_name} phase error: {exc}")

    # ---------------- 1. SEARCH ----------------
    def phase_search():
        nav(page, BASE)
        hero = page.locator("form:has(input[placeholder='Service, injector, or clinic'])")
        hero_count = hero.count()
        header_probe = page.evaluate("""(() => {
            const h = document.querySelector('header');
            if (!h) return null;
            const btns = Array.from(h.querySelectorAll('button, a')).map(b => ({
                aria: b.getAttribute('aria-label'), title: b.title,
                text: (b.innerText || '').trim().slice(0, 30)
            })).filter(b => (b.aria && /search/i.test(b.aria)) || /search/i.test(b.title));
            const inputs = Array.from(h.querySelectorAll('input')).map(i => ({
                placeholder: i.placeholder, type: i.type
            }));
            return {searchBtns: btns, inputs};
        })()""")
        log(f"hero_form_count={hero_count} header_search_probe={json.dumps(header_probe)}")

        search_results = {}
        if hero_count:
            def run_query(q, key):
                for attempt in range(2):
                    nav(page, BASE)
                    hq = page.locator("form:has(input[placeholder='Service, injector, or clinic'])")
                    if not hq.count():
                        return {"error": "hero form not found on retry"}
                    hq.locator("input").first.fill(q)
                    hq.locator("input").first.press("Enter")
                    page.wait_for_timeout(4500)
                    if "/search" in page.url:
                        break
                u = page.url
                body = body_text(page)
                m = re.search(r"(\d[\d,]*)\s+(results?|clinics?|injectors?|matches?|practices?)[^.\n]{0,60}", body, re.I)
                empty_txt = re.search(r"([^\n]*(no results|nothing found|0 results)[^\n]*)", body, re.I)
                loc_region = re.search(r"(location[^\n]{0,80})", body, re.I)
                return {
                    "url": u, "count_text": m.group(0) if m else None,
                    "empty_state": empty_txt.group(1).strip()[:120] if empty_txt else None,
                    "location_hint": loc_region.group(1).strip()[:100] if loc_region else None,
                    "pageerrors": len(page_errors),
                }
            search_results["botox"] = run_query("Botox", "botox")
            R["shots"]["search-botox"] = shot(page, slug, "t11-search", "botox-results")
            log(f"search Botox -> {json.dumps(search_results['botox'])}")
            search_results["austin"] = run_query("Austin", "austin")
            R["shots"]["search-austin"] = shot(page, slug, "t11-search", "austin-results")
            log(f"search Austin -> {json.dumps(search_results['austin'])}")
        else:
            search_results["botox"] = {"error": "no hero search form on mobile"}
            log("NO hero search form found on mobile homepage")
        R["search"] = search_results

    # ---------------- 2. NEWSLETTER ----------------
    def phase_newsletter():
        nav(page, BASE)
        nl = page.locator("form:has(#nl-email)")
        nl_count = nl.count()
        R["newsletter"] = {"form_count": nl_count}
        if not nl_count:
            log("NO #nl-email newsletter form found in footer")
            return
        nl.locator("#nl-email").fill("not-an-email")
        try:
            nl.get_by_role("button", name="Subscribe").click()
        except Exception:
            nl.locator("button[type=submit], button").first.click()
        page.wait_for_timeout(2500)
        v_inv = page.evaluate("""(() => {
            const i = document.querySelector('#nl-email');
            return {valid: i.validity.valid, msg: i.validationMessage,
                    focused: document.activeElement === i};
        })()""")
        R["shots"]["nl-invalid"] = shot(page, slug, "t11-newsletter", "invalid-email")
        nl.locator("#nl-email").fill("")
        try:
            nl.get_by_role("button", name="Subscribe").click()
        except Exception:
            nl.locator("button[type=submit], button").first.click()
        page.wait_for_timeout(2500)
        v_empty = page.evaluate("""(() => {
            const i = document.querySelector('#nl-email');
            return {valid: i.validity.valid, msg: i.validationMessage};
        })()""")
        R["shots"]["nl-empty"] = shot(page, slug, "t11-newsletter", "empty-submit")
        R["newsletter"].update({"invalid": v_inv, "empty": v_empty})
        log(f"newsletter invalid={json.dumps(v_inv)} empty={json.dumps(v_empty)}")

    # ---------------- 3. MOBILE NAV ----------------
    def phase_nav():
        nav(page, BASE)
        burger = page.locator(TOGGLE_CSS)
        R["nav"] = {"burger_count": burger.count()}
        if not burger.count():
            log("NO hamburger button found")
            return
        burger.first.click()
        page.wait_for_timeout(1500)
        expanded = toggle_state(page)
        menu_links = page.evaluate(VISIBLE_ANCHORS_JS)
        R["nav"]["expanded"] = expanded
        R["nav"]["menu_links"] = menu_links
        log(f"menu expanded={expanded} visible_links={len(menu_links)}")

        target = None
        for l in menu_links:
            p = norm_url(l["href"]).split("?")[0].replace(BASE, "")
            if l["href"].startswith(BASE) and p and p not in BROKEN and p not in ("/", "/login"):
                target = l
                break
        if not target:
            R["nav"]["error"] = "no usable menu link found"
            log("no usable menu link found")
            return
        href = target["href"]
        R["nav"]["clicked_text"] = target["text"]
        R["nav"]["clicked_href"] = href
        log(f"nav target: {target['text']!r} -> {href}")
        tap_result = mouse_tap(page, href)
        tap_ok = tap_result is not None and norm_url(tap_result) == norm_url(href)
        exp_after = toggle_state(page)
        if tap_ok:
            R["nav"].update({
                "result_url": tap_result, "nav_ok": True,
                "menu_closed": exp_after == "false", "expanded_after": exp_after,
                "tap_method": "mouse",
            })
            R["shots"]["nav"] = shot(page, slug, "t11-nav", "after-menu-click")
            log(f"nav target={target['text']!r} nav_ok=True (tap navigated) url={tap_result}")
            return
        covered = page.evaluate("""(href) => {
            const h = document.querySelector('header');
            const a = Array.from(h.querySelectorAll('a[href]')).find(x => x.href === href);
            if (!a) return null;
            const r = a.getBoundingClientRect();
            const cx = r.left + r.width/2, cy = r.top + r.height/2;
            const el = document.elementFromPoint(cx, cy);
            return {center: {x: Math.round(cx), y: Math.round(cy)},
                    coveredBy: el && el !== a && !a.contains(el) ? {tag: el.tagName,
                        text: (el.innerText||'').trim().slice(0,25),
                        cls: (el.className||'').toString().slice(0,60)} : null};
        }""", href)
        R["nav"].update({
            "nav_ok": False, "menu_closed": False,
            "result_url": tap_result or page.url,
            "covered_by": covered.get("covered_by") if covered else None,
            "tap_center": covered.get("center") if covered else None,
        })
        R["shots"]["nav"] = shot(page, slug, "t11-nav", "after-menu-tap")
        log(f"nav: tap on {target['text']!r} landed at {tap_result} (target {href}); covered_by={json.dumps(covered.get('covered_by')) if covered else None}")

    # ---------------- 4. TOUCH TARGETS (functional) ----------------
    def phase_touch():
        nav(page, BASE)
        clinic_links = page.evaluate("""(() => {
            return Array.from(document.querySelectorAll("a[href*='/clinics/']")).map(a => ({
                text: (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60),
                href: a.href
            }));
        })()""")
        seen = set()
        uniq = []
        for l in clinic_links:
            if l["href"] not in seen:
                seen.add(l["href"])
                uniq.append(l)
        R["touch"] = {"clinic_links_found": len(uniq),
                      "samples": [{"text": l["text"][:40], "href": l["href"]} for l in uniq[:4]]}
        log(f"clinic links found: {len(uniq)}")
        taps = []
        for l in uniq[:2]:
            try:
                nav(page, BASE)
                result = mouse_tap(page, l["href"])
                ok = result is not None and norm_url(result).rstrip("/").startswith(BASE + "/clinics/")
                taps.append({"type": "clinic", "href": l["href"], "navigated": ok,
                             "result_url": result or "", "h1_count": page.locator("h1").count()})
                log(f"clinic tap {l['href'].split('/')[-1]} navigated={ok}")
            except Exception as exc:
                taps.append({"type": "clinic", "href": l["href"], "navigated": False,
                             "error": str(exc)[:120]})
        nav(page, BASE)
        footer_links = page.evaluate("""(() => {
            const f = document.querySelector('footer');
            if (!f) return [];
            return Array.from(f.querySelectorAll('a[href]')).map(a => ({
                text: (a.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40),
                href: a.href
            })).filter(x => x.href.startsWith('%s'));
        })""" % BASE)
        fseen, funiq = set(), []
        for l in footer_links:
            p = norm_url(l["href"]).split("?")[0].replace(BASE, "")
            if l["href"] not in fseen and p not in BROKEN and p:
                fseen.add(l["href"])
                funiq.append(l)
        for l in funiq[:2]:
            try:
                nav(page, BASE)
                result = mouse_tap(page, l["href"])
                ok = result is not None and result.startswith(BASE) and norm_url(result) != norm_url(BASE)
                taps.append({"type": "footer", "text": l["text"], "href": l["href"],
                             "navigated": ok, "result_url": result or ""})
                log(f"footer tap {l['text']!r} navigated={ok} -> {result}")
            except Exception as exc:
                taps.append({"type": "footer", "text": l["text"], "href": l["href"],
                             "navigated": False, "error": str(exc)[:120]})
        R["touch"]["taps"] = taps
        R["touch"]["all_navigated"] = all(t["navigated"] for t in taps) and len(taps) == 4
        R["shots"]["touch"] = shot(page, slug, "t11-touch", "after-footer-tap")

    # ---------------- 5. BACK / FORWARD ----------------
    def phase_backfwd():
        nav(page, BASE)
        hero_vis_home = page.get_by_text("Find Your Injector.", exact=False).count() > 0
        clinic_links = page.evaluate("""() => {
            const seen = new Set();
            return Array.from(document.querySelectorAll("a[href*='/clinics/']")).map(a => a.href)
                .filter(h => { if (seen.has(h)) return false; seen.add(h); return true; });
        }""")
        if not clinic_links:
            R["backfwd"] = {"error": "no clinic link to navigate into"}
            log("no clinic link for back/fwd test")
            return
        try:
            result = mouse_tap(page, clinic_links[0])
            if result is None:
                R["backfwd"] = {"error": "clinic link not tappable (no rect found)"}
                log("back/fwd: clinic link not found for tap")
                return
            detail_url = result
            page.go_back()
            page.wait_for_timeout(3500)
            back_url = norm_url(page.url)
            back_hero = page.get_by_text("Find Your Injector.", exact=False).count() > 0
            back_ok = back_url == norm_url(BASE) and back_hero
            R["backfwd"] = {
                "detail_url": detail_url, "back_url": page.url,
                "back_ok": back_ok, "back_hero": back_hero,
                "back_title": page.title(),
            }
            R["shots"]["back"] = shot(page, slug, "t11-back-forward", "after-back-home")
            log(f"back: ok={back_ok} url={page.url} hero={back_hero} (home hero pre-nav={hero_vis_home})")
        except Exception as exc:
            R["backfwd"] = {"error": str(exc)[:200]}
            log(f"back/fwd failed: {exc}")

    # ---------------- 6. STATS ----------------
    def phase_stats():
        nav(page, BASE)
        labels = ["Clinics Listed", "Brands Listed", "Markets Covered",
                  "Treatment Guides", "Metro Markets", "Years Independent"]
        counters_script = """(labels) => {
            const out = {};
            labels.forEach(l => {
                const el = Array.from(document.querySelectorAll('*')).find(e => (e.innerText||'').trim() === l);
                if (el && el.parentElement) out[l] = el.parentElement.innerText.trim().replace(/\\n+/g,' ').slice(0,80);
            });
            return out;
        }"""
        before = page.evaluate(counters_script, labels)
        try:
            page.get_by_text("Clinics Listed", exact=True).first.scroll_into_view_if_needed()
        except Exception:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(3200)
        after = page.evaluate(counters_script, labels)
        R["stats"] = {"before": before, "after": after}
        R["shots"]["stats"] = shot(page, slug, "t11-stats", "counters-after-3s")
        log(f"stats before={json.dumps(before)} after={json.dumps(after)}")

    # ---------------- 7. EMPTY-STATE ----------------
    def phase_empty():
        R["empty"] = {"home_empty_state_expected": True}
        botox_url = R.get("search", {}).get("botox", {}).get("url")
        if not botox_url:
            log("empty-state: no botox search url to recheck")
            return
        page.goto(botox_url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        body = body_text(page)
        graceful = bool(re.search(r"(no results|0 results|nothing found|no clinics)", body, re.I))
        R["empty"].update({
            "search_empty_state": graceful,
            "pageerrors": len(page_errors),
            "blank": not body.strip(),
        })
        log(f"empty-state search page: graceful={graceful} pageerrors={len(page_errors)} blank={not body.strip()}")

    safe("search", phase_search)
    safe("newsletter", phase_newsletter)
    safe("nav", phase_nav)
    safe("touch", phase_touch)
    safe("backfwd", phase_backfwd)
    safe("stats", phase_stats)
    safe("empty", phase_empty)

    ctx.close()
    return R


FINDINGS_PATH = ROOT / "data" / "findings.json"


def load_findings():
    return json.loads(FINDINGS_PATH.read_text(encoding="utf-8"))


def save_findings(entries):
    tmp = FINDINGS_PATH.with_suffix(FINDINGS_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    tmp.replace(FINDINGS_PATH)


def shot_exists(p):
    if not p:
        return False
    return (ROOT / p).exists()


def main() -> int:
    unix = int(time.time())
    results = {}
    with sync_playwright() as p:
        for device, slug in DEVICES:
            print(f"\n########## {device} ({slug}) ##########")
            browser = p.chromium.launch(headless=True)
            try:
                results[device] = run_device(p, browser, device, slug)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

    out = ROOT / "data" / "t11-mobile-functional-results.json"
    out.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nper-device results written to {out}")

    entries = load_findings()
    start_len = len(entries)
    n = 1

    def append(entry):
        entries.append(entry)
        print(f"appended {entry['id']} | {entry['severity']} | {entry['title']}")

    r13 = results.get("iPhone 13", {})
    r7 = results.get("Pixel 7", {})

    # ---- SEARCH: Botox 0 results ----
    b13 = r13.get("search", {}).get("botox", {})
    b7 = r7.get("search", {}).get("botox", {})
    a13 = r13.get("search", {}).get("austin", {})
    a7 = r7.get("search", {}).get("austin", {})
    both_botox_empty = (
        b13 and b7 and
        (b13.get("empty_state") or "0 result" in str(b13.get("count_text"))) and
        (b7.get("empty_state") or "0 result" in str(b7.get("count_text")))
    )
    print(f"\n== CONSOLIDATION == botox13={json.dumps(b13)} botox7={json.dumps(b7)}")
    print(f"austin13={json.dumps(a13)} austin7={json.dumps(a7)}")

    if b13.get("error") or b7.get("error"):
        print("search: inconclusive on at least one device — no finding")
    elif both_botox_empty:
        shot_p = (r13.get("shots", {}).get("search-botox") or
                  r7.get("shots", {}).get("search-botox") or "")
        austin_note = ""
        if (a13.get("empty_state") or "0 result" in str(a13.get("count_text"))) and \
           (a7.get("empty_state") or "0 result" in str(a7.get("count_text"))):
            austin_note = (" A valid-location query ('Austin') also returned 0 results on both "
                           "devices, consistent with the empty clinics directory.")
        elif a13 or a7:
            austin_note = (f" A location query ('Austin') resolved differently: "
                           f"i13={json.dumps(a13.get('count_text') or a13.get('empty_state'))}, "
                           f"p7={json.dumps(a7.get('count_text') or a7.get('empty_state'))}.")
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": (b13.get("url") or BASE + "/search"),
            "severity": "MEDIUM",
            "title": "Mobile site-wide search returns 0 results for 'Botox' (same as desktop)",
            "actual": ("On both iPhone 13 and Pixel 7, searching 'Botox' via the directory search "
                       "returns 0 results (empty state text present) — identical to the desktop "
                       "behavior filed as a desktop HIGH (search returns 0 results for Botox). "
                       f"Botox results text: i13={json.dumps(b13.get('count_text') or b13.get('empty_state'))}, "
                       f"p7={json.dumps(b7.get('count_text') or b7.get('empty_state'))}."),
            "expected": "A valid brand query like 'Botox' should return matching clinics/injectors given the site claims 17,020+ verified clinics.",
            "repro_steps": ("1) Open https://www.injector.world/ on an iPhone 13 or Pixel 7.\n"
                            "2) Tap the directory search field, type 'Botox'.\n"
                            "3) Tap Search.\n"
                            "4) Observe the results page reports 0 results."),
            "screenshot_path": shot_p,
            "notes": "Matches desktop T7 HIGH 'Search returns 0 results for a valid brand query (Botox)'. "
                     "Same defect on mobile => MEDIUM mobile finding with also_present_on desktop. " + austin_note,
            "affected_pages": [BASE, (b13.get("url") or b7.get("url") or BASE)],
            "also_present_on": "desktop",
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("Botox search NOT 0-result on mobile — recording not_reproducible")
        shot_p = (r13.get("shots", {}).get("search-botox") or
                  r7.get("shots", {}).get("search-botox") or "")
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": BASE,
            "severity": "LOW",
            "title": "Site-wide search 'Botox' NOT reproduced as 0-results on mobile",
            "actual": f"i13={json.dumps(b13)} p7={json.dumps(b7)}",
            "expected": "Search returns results; desktop T7 showed 0 results.",
            "repro_steps": "1) Open homepage on mobile. 2) Search 'Botox'. 3) Read results count.",
            "screenshot_path": shot_p,
            "notes": "not_reproducible: mobile search behavior differs from the desktop T7 HIGH.",
            "affected_pages": [BASE],
            "status": "not_reproducible",
            "created_at": iso_now(),
        })
        n += 1

    # ---- NEWSLETTER ----
    nl13 = r13.get("newsletter", {})
    nl7 = r7.get("newsletter", {})
    nl_ok = (
        nl13.get("form_count") and nl7.get("form_count") and
        nl13.get("invalid", {}).get("valid") is False and
        nl7.get("invalid", {}).get("valid") is False and
        nl13.get("empty", {}).get("valid") is False and
        nl7.get("empty", {}).get("valid") is False
    )
    print(f"== NEWSLETTER == i13={json.dumps(nl13)} p7={json.dumps(nl7)} nl_ok={nl_ok}")
    if nl13.get("form_count") == 0 or nl7.get("form_count") == 0:
        print("newsletter: form missing on a device — no finding")
    elif not nl_ok:
        shot_p = (r13.get("shots", {}).get("nl-invalid") or
                  r7.get("shots", {}).get("nl-invalid") or "")
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": BASE,
            "severity": "MEDIUM",
            "title": "Mobile newsletter form does not reject empty/invalid email",
            "actual": (f"iPhone 13: invalid valid={nl13.get('invalid', {}).get('valid')} msg={nl13.get('invalid', {}).get('msg')!r}, "
                       f"empty valid={nl13.get('empty', {}).get('valid')} msg={nl13.get('empty', {}).get('msg')!r}. "
                       f"Pixel 7: invalid valid={nl7.get('invalid', {}).get('valid')} msg={nl7.get('invalid', {}).get('msg')!r}, "
                       f"empty valid={nl7.get('empty', {}).get('valid')} msg={nl7.get('empty', {}).get('msg')!r}."),
            "expected": "Newsletter form must reject empty and malformed emails with a visible validation error (native HTML5 validation works on desktop).",
            "repro_steps": ("1) Open homepage on mobile. 2) Scroll to footer newsletter. "
                            "3) Type 'not-an-email', tap Subscribe. 4) Clear and tap Subscribe again."),
            "screenshot_path": shot_p,
            "notes": "Desktop T7 verified native HTML5 validation; mobile deviates.",
            "affected_pages": [BASE],
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("newsletter validation OK on both devices (native HTML5)")

    # ---- NAV ----
    nav13, nav7 = r13.get("nav", {}), r7.get("nav", {})
    nav_ok = nav13.get("nav_ok") and nav7.get("nav_ok") and \
        nav13.get("menu_closed") and nav7.get("menu_closed")
    print(f"== NAV == i13={json.dumps({k: nav13.get(k) for k in ('nav_ok','menu_closed','clicked_text','result_url','burger_count','phase_error')})} "
          f"p7={json.dumps({k: nav7.get(k) for k in ('nav_ok','menu_closed','clicked_text','result_url','burger_count','phase_error')})}")
    if nav13.get("burger_count") == 0 or nav7.get("burger_count") == 0:
        print("nav: hamburger missing — no finding (T10 covered menu rendering)")
    elif not nav_ok:
        shot_p = r13.get("shots", {}).get("nav") or r7.get("shots", {}).get("nav") or ""
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": BASE,
            "severity": "HIGH",
            "title": "Mobile hamburger menu links untappable — dropdown painted behind page content",
            "actual": (f"On both devices, opening the hamburger menu and tapping the menu link "
                       f"'{nav13.get('clicked_text')}' ({nav13.get('clicked_href')}) does NOT navigate: "
                       f"a real tap at the link center (y={json.dumps((nav13.get('tap_center') or {}).get('y'))}px) "
                       f"hit {json.dumps(nav13.get('covered_by'))} and landed on {nav13.get('result_url')} "
                       f"(iPhone 13); on Pixel 7 it landed on {nav7.get('result_url')}. The dropdown panel "
                       f"and all its ancestors are position:static / z-index:auto while the hero <section> "
                       f"is position:relative, so the hero (incl. the 'Ask AI' form) paints above the menu "
                       f"and covers its links (elementFromPoint at link centers returns the hero element)."),
            "expected": "Tapping a nav link in the opened hamburger menu should navigate to the target page; the menu must paint above the page content.",
            "repro_steps": ("1) Open https://www.injector.world/ on an iPhone 13 or Pixel 7.\n"
                            "2) Tap the hamburger button (aria-label='Open menu').\n"
                            "3) Tap a menu link (e.g. 'Botox').\n"
                            "4) Observe the tap does not navigate — it activates the underlying hero "
                            "'Ask AI' form / content instead (stays on '/' or focuses the AI input)."),
            "screenshot_path": shot_p,
            "notes": "Primary mobile navigation is unusable. Root cause: menu dropdown panel has no "
                     "positioning/z-index (static/z-auto chain); the hero section is position:relative "
                     "and paints above it. Menu toggle itself works (opens/closes the panel). "
                     "Evidence: covered_by + tap landing URL on both devices.",
            "affected_pages": [BASE, (nav13.get("clicked_href") or BASE)],
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("mobile nav functional OK on both devices")

    # ---- TOUCH ----
    t13, t7 = r13.get("touch", {}), r7.get("touch", {})
    touch_ok = t13.get("all_navigated") and t7.get("all_navigated")
    print(f"== TOUCH == i13 all_navigated={t13.get('all_navigated')} taps={len(t13.get('taps', []))} err={t13.get('phase_error')} "
          f"p7 all_navigated={t7.get('all_navigated')} taps={len(t7.get('taps', []))} err={t7.get('phase_error')}")
    if not touch_ok:
        shot_p = r13.get("shots", {}).get("touch") or r7.get("shots", {}).get("touch") or ""
        t13_fail = [x for x in t13.get("taps", []) if not x["navigated"]]
        t7_fail = [x for x in t7.get("taps", []) if not x["navigated"]]
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": BASE,
            "severity": "HIGH",
            "title": "Interactive card/footer link taps do not navigate on mobile",
            "actual": f"Failed taps i13={json.dumps(t13_fail, default=str)} p7={json.dumps(t7_fail, default=str)}",
            "expected": "Tapping clinic 'View details' cards and footer links should navigate to the destination page.",
            "repro_steps": ("1) Open homepage on mobile. 2) Tap a Featured Clinic 'View details' card. "
                            "3) Tap footer links. 4) Observe whether navigation occurs."),
            "screenshot_path": shot_p,
            "affected_pages": [BASE],
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("touch targets functional OK on both devices (tap -> navigates)")

    # ---- BACK/FWD ----
    bf13, bf7 = r13.get("backfwd", {}), r7.get("backfwd", {})
    bf_ok = bf13.get("back_ok") and bf7.get("back_ok")
    print(f"== BACK/FWD == i13={json.dumps(bf13)} p7={json.dumps(bf7)}")
    if "error" not in bf13 and "error" not in bf7 and not bf_ok:
        shot_p = r13.get("shots", {}).get("back") or r7.get("shots", {}).get("back") or ""
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": BASE,
            "severity": "MEDIUM",
            "title": "Browser back from clinic detail does not restore homepage on mobile",
            "actual": (f"iPhone 13: back_url={bf13.get('back_url')} back_ok={bf13.get('back_ok')} "
                       f"hero={bf13.get('back_hero')}. "
                       f"Pixel 7: back_url={bf7.get('back_url')} back_ok={bf7.get('back_ok')} "
                       f"hero={bf7.get('back_hero')}."),
            "expected": "Browser back from a clinic detail page should restore the homepage with content.",
            "repro_steps": ("1) Open homepage on mobile. 2) Tap a clinic 'View details' card. "
                            "3) Tap browser back. 4) Observe whether the homepage is restored."),
            "screenshot_path": shot_p,
            "affected_pages": [BASE, (bf13.get("detail_url") or BASE)],
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("back/fwd OK on both devices")

    # ---- STATS ----
    st13, st7 = r13.get("stats", {}), r7.get("stats", {})
    def stats_bad(st):
        vals = " ".join(str(v) for v in (st.get("after") or {}).values())
        return bool(re.search(r"(^|\s)0\+($|\s)", vals)) or "0yrs" in vals
    st_bad = stats_bad(st13) or stats_bad(st7)
    print(f"== STATS == i13_after={json.dumps(st13.get('after'))} p7_after={json.dumps(st7.get('after'))} bad={st_bad}")
    if st_bad:
        shot_p = r13.get("shots", {}).get("stats") or r7.get("shots", {}).get("stats") or ""
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": BASE,
            "severity": "MEDIUM",
            "title": "Homepage stats counters stuck at 0+ after scroll on mobile",
            "actual": (f"After scrolling the stats band into view and waiting 3s: "
                       f"iPhone 13 after={json.dumps(st13.get('after'))}; "
                       f"Pixel 7 after={json.dumps(st7.get('after'))}."),
            "expected": "Stats counters should animate to real values (17,020+ clinics, 10+ brands, 2767+ markets) after scroll.",
            "repro_steps": ("1) Open homepage on mobile. 2) Scroll stats band into view. "
                            "3) Wait 3s and read the counter values."),
            "screenshot_path": shot_p,
            "affected_pages": [BASE],
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("stats count-up OK on both devices (matches desktop T7) — no finding")

    # ---- EMPTY-STATE ----
    e13, e7 = r13.get("empty", {}), r7.get("empty", {})
    print(f"== EMPTY == i13={json.dumps(e13)} p7={json.dumps(e7)}")
    # Homepage directory empty state is EXPECTED (known); only file if a search
    # results page crashed (pageerror/blank).
    e_bad = (
        (e13.get("pageerrors", 0) > 0 and not e13.get("search_empty_state")) or
        (e7.get("pageerrors", 0) > 0 and not e7.get("search_empty_state"))
    )
    if e_bad:
        append({
            "id": f"mobile-t11-{unix}-{n}", "device": "iphone-13, pixel-7",
            "url": (b13.get("url") or BASE),
            "severity": "MEDIUM",
            "title": "No-results search page renders blank/crashes on mobile",
            "actual": f"i13={json.dumps(e13)} p7={json.dumps(e7)}",
            "expected": "A no-results search should render a graceful empty-state message, not a blank/crashing page.",
            "repro_steps": "1) Search 'Botox' on mobile. 2) Observe the 0-results page.",
            "screenshot_path": (r13.get("shots", {}).get("search-botox") or ""),
            "affected_pages": [(b13.get("url") or BASE)],
            "created_at": iso_now(),
        })
        n += 1
    else:
        print("empty-state graceful on both devices — no finding")

    save_findings(entries)
    print(f"\nFINDINGS WRITTEN. total={len(entries)} (was {start_len}), appended={n - 1}")

    missing = [x["id"] for x in entries[start_len:] if not shot_exists(x.get("screenshot_path"))]
    if missing:
        print("WARNING missing screenshots:", missing)
    mobile = [x for x in entries if str(x["device"]).lower().startswith(("iphone", "pixel")) or "mobile" in str(x["device"]).lower()]
    print(f"mobile findings now: {len(mobile)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
