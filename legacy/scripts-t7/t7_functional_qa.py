#!/usr/bin/env python3
import sys, json, time, re, os
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, "/home/heyatoy/Projects/testing/scripts")
from harness import (
    desktop_context, append_finding,
    NAV_TIMEOUT_MS, NETWORKIDLE_CAP_MS, SETTLE_MS, EVIDENCE_DIR,
)

BASE = "https://www.injector.world"
ROOT = Path("/home/heyatoy/Projects/testing")
EVID = ROOT / "evidence" / "desktop"

def ts():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

def nav(page, url):
    resp = page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_CAP_MS)
    except Exception:
        pass
    page.wait_for_timeout(SETTLE_MS)
    return resp

def shot(page, scenario, name):
    d = EVID / scenario
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}-{ts()}.png"
    page.screenshot(path=str(p), full_page=True)
    return str(p)

page_errors = []
console_lines = []
req_failures = []

def collect(page):
    page.on("console", lambda m: console_lines.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: page_errors.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: req_failures.append(r.url))

def reset_collectors():
    page_errors.clear()
    console_lines.clear()
    req_failures.clear()

COUNTER_SCRIPT = """(labels) => {
    const out = {};
    labels.forEach(l => {
        const el = Array.from(document.querySelectorAll('*')).find(e => (e.innerText||'').trim() === l);
        if (el && el.parentElement) out[l] = el.parentElement.innerText.trim().replace(/\\n+/g,' ').slice(0,80);
    });
    return out;
}"""

def finding_exists(title, url):
    with open(ROOT / "data" / "findings.json") as fh:
        existing = json.load(fh)
    return any(x.get("device") == "desktop" and x.get("title") == title and x.get("url") == url for x in existing)

def finding_exists(title, url):
    with open(ROOT / "data" / "findings.json") as fh:
        existing = json.load(fh)
    return any(x.get("device") == "desktop" and x.get("title") == title and x.get("url") == url for x in existing)

_orig_append = append_finding
def append_finding(device, url, severity, title, actual, expected, repro_steps, screenshot_path="", notes="", affected_pages=None):
    if finding_exists(title, url):
        print(f"  [dedup] skipping existing finding: {title[:60]} @ {url}")
        return None
    return _orig_append(device=device, url=url, severity=severity, title=title, actual=actual,
                        expected=expected, repro_steps=repro_steps, screenshot_path=screenshot_path,
                        notes=notes, affected_pages=affected_pages)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = desktop_context(browser)
    page = ctx.new_page()
    collect(page)

    # ============ PHASE 1: NAVIGATION ============
    print("=== PHASE 1: NAVIGATION ===")
    reset_collectors()
    nav(page, BASE)
    home_links = page.evaluate("""Array.from(document.querySelectorAll('header a, nav a, footer a')).map(a => a.href)""")
    same_site = sorted(set(h for h in home_links if h.startswith(BASE)))
    print(f"unique same-site header+footer links: {len(same_site)}")
    nav_failures = []
    if os.environ.get("T7_SKIP_NAV"):
        print("T7_SKIP_NAV set — skipping bulk nav-link crawl (already verified + findings filed)")
    else:
        for href in same_site:
            reset_collectors()
            try:
                resp = page.goto(href, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                status = resp.status if resp else None
                if status is None or status >= 400:
                    nav_failures.append({"href": href, "status": status, "final": page.url, "title": page.title(), "errs": list(page_errors)})
            except Exception as exc:
                nav_failures.append({"href": href, "status": "exception", "final": page.url, "title": page.title(), "errs": [str(exc)[:200]]})
    if nav_failures:
        print("NAV FAILURES:", json.dumps(nav_failures, indent=1))
        for f in nav_failures:
            shot_p = None
            try:
                nav(page, f["href"])
                shot_p = shot(page, "navigation", f"broken-{f['href'].replace(BASE,'').strip('/').replace('/','-') or 'home'}")
            except Exception:
                pass
            append_finding(
                device="desktop",
                url=f["href"],
                severity="HIGH",
                title="Broken navigation: header/footer link does not reach a valid page",
                actual=f"Link to {f['href']} resolved to status {f['status']} (final URL {f['final']}){' with console errors: ' + '; '.join(f['errs'][:3]) if f['errs'] else ''}",
                expected="All header/footer navigation links should resolve to HTTP 200 with the destination page rendered",
                repro_steps=f"1. Load {BASE}/\n2. Click navigation link {f['href']}\n3. Observe the resulting page",
                screenshot_path=shot_p or "",
                affected_pages=[BASE, f["href"]],
            )
    else:
        print("ALL SAME-SITE NAV LINKS OK (200)")
    nav(page, BASE)

    back_to_top = page.get_by_text("Back to top", exact=True).first
    print("back-to-top count:", back_to_top.count())
    if back_to_top.count():
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(600)
        before = page.evaluate("window.scrollY")
        back_to_top.click()
        page.wait_for_timeout(1500)
        after = page.evaluate("window.scrollY")
        url_after = page.url
        print(f"back-to-top: before={before} after={after} url={url_after}")
        if after > 10 or url_after != BASE:
            shot_p = shot(page, "navigation", "back-to-top-fail")
            append_finding(
                device="desktop", url=BASE, severity="MEDIUM",
                title="Back to top control does not scroll to top",
                actual=f"After clicking 'Back to top', window.scrollY={after} (was {before}); page URL {url_after}",
                expected="Clicking 'Back to top' should scroll window.scrollY to 0 without navigating",
                repro_steps="1. Load homepage\n2. Scroll to bottom\n3. Click 'Back to top'",
                screenshot_path=shot_p, affected_pages=[BASE],
            )
        else:
            print("back-to-top OK")

    for sub in ["/brands/botox", "/guides/botox", "/services/botox", "/news"]:
        nav(page, BASE + sub)
        bc = page.evaluate("""Array.from(document.querySelectorAll('nav[aria-label], [class*=breadcrumb]')).map(e => ({aria: e.getAttribute('aria-label'), cls: (e.className||'').slice(0,60), text: (e.innerText||'').trim().replace(/\\n+/g,' | ').slice(0,150)}))""")
        print(f"breadcrumbs on {sub}: {json.dumps(bc)}")

    # ============ PHASE 2: SEARCH ============
    print("=== PHASE 2: SEARCH ===")
    hero_form = lambda pg: pg.locator("form:has(input[placeholder='Service, injector, or clinic'])")

    def do_search(query):
        reset_collectors()
        nav(page, BASE)
        f = hero_form(page)
        if query is not None:
            f.locator("input").first.fill(query)
        f.get_by_role("button", name="Search").click()
        page.wait_for_timeout(4500)
        return {"url": page.url, "errs": list(page_errors), "console": list(console_lines)}

    variants = [
        ("botox", "Botox"),
        ("empty", ""),
        ("special-chars", "%%%??##"),
        ("long-200", "x" * 200),
        ("no-results", "zzzzqqqnotfound999"),
    ]
    for name, q in variants:
        r = do_search(q)
        print(f"search[{name}]: url={r['url']} pageerrors={len(r['errs'])} console_errs={len(r['console'])}")
        if r["errs"]:
            print("   PAGEERRORS:", r["errs"][:5])
        shot_p = shot(page, "search", f"variant-{name}")
        status = page.evaluate("performance.getEntriesByType('navigation')[0].responseStatus ?? 0")
        body_txt = page.locator("body").inner_text()
        no_res = "no results" in body_txt.lower() or "nothing found" in body_txt.lower() or "no clinics" in body_txt.lower()
        print(f"   status={status} no_results_text={no_res}")
        if "/search" not in r["url"]:
            append_finding(
                device="desktop", url=r["url"], severity="HIGH",
                title="Search does not navigate to results page",
                actual=f"Submitting search query {q!r} left the page at {r['url']} instead of a /search results URL",
                expected="Submitting a search should navigate to /search?q=... and render results",
                repro_steps=f"1. Load {BASE}/\n2. Type {q!r} in the directory search box\n3. Click Search",
                screenshot_path=shot_p, affected_pages=[BASE, r["url"]],
            )
        elif r["errs"]:
            append_finding(
                device="desktop", url=r["url"], severity="MEDIUM",
                title="Search page emits JavaScript errors",
                actual=f"Query {q!r} caused page errors: {'; '.join(r['errs'][:3])}",
                expected="Search results page should load without JavaScript errors",
                repro_steps=f"1. Load {BASE}/\n2. Search for {q!r}\n3. Observe console",
                screenshot_path=shot_p, affected_pages=[BASE, r["url"]],
            )
        if name == "no-results":
            results_region = page.evaluate("""(() => {
                const b = document.body.innerText;
                const m = b.match(/(\\d[\\d,]*) (result|clinic|injector|practice|match)[^\\n]{0,60}/i);
                return {sample: (m?m[0]:''), hasEmptyState: /no results|no clinics|nothing found/i.test(b)};
            })()""")
            print("   no-results region:", json.dumps(results_region))
        if name == "botox":
            botox_info = page.evaluate("""(() => {
                const b = document.body.innerText;
                const m = b.match(/(\\d[\\d,]*) (results?|clinics?|injectors?|practices?|matches?)[^\\n]{0,80}/i);
                const cards = document.querySelectorAll('a[href*="/clinics/"], a[href*="/brands/"], a[href*="/guides/"]');
                const idx = b.indexOf('result');
                return {matchText: m?m[0]:null, sampleCards: cards.length, bodyAround: idx>=0 ? b.slice(Math.max(0,idx-120), idx+160).replace(/\\n+/g,' ') : b.slice(0,200)};
            })()""")
            print("   botox results info:", json.dumps(botox_info))
            if botox_info.get("matchText") and botox_info["matchText"].startswith("0 "):
                append_finding(
                    device="desktop", url=r["url"], severity="HIGH",
                    title="Search returns 0 results for a valid brand query (Botox)",
                    actual=f"Searching 'Botox' on the directory search returned {botox_info['matchText']!r}; page context: {botox_info.get('bodyAround','')[:180]!r}. Site simultaneously claims 17,020+ verified clinics.",
                    expected="A valid brand query like 'Botox' should return matching clinics/injectors given the site's 17,020+ clinics claim",
                    repro_steps="1. Load homepage\n2. Type 'Botox' in the directory search\n3. Click Search\n4. Observe the results count",
                    screenshot_path=shot_p,
                    notes="Consistent with the empty clinics directory (0 verified clinics on /clinics and homepage).",
                    affected_pages=[BASE, r["url"]],
                )
            else:
                print("   botox returned non-zero results:", botox_info.get("matchText"))

    # ============ PHASE 3: NEWSLETTER ============
    print("=== PHASE 3: NEWSLETTER ===")
    reset_collectors()
    nav(page, BASE)
    nl_form = page.locator("form:has(#nl-email)")
    nl_form.locator("#nl-email").fill("not-an-email")
    nl_form.get_by_role("button", name="Subscribe").click()
    page.wait_for_timeout(2500)
    v_invalid = page.evaluate("""(() => { const i = document.querySelector('#nl-email'); return {valid: i.validity.valid, msg: i.validationMessage, focused: document.activeElement === i}; })()""")
    shot_inv = shot(page, "newsletter", "invalid-email-validation")
    print("invalid:", json.dumps(v_invalid))
    nl_form.locator("#nl-email").fill("")
    nl_form.get_by_role("button", name="Subscribe").click()
    page.wait_for_timeout(2500)
    v_empty = page.evaluate("""(() => { const i = document.querySelector('#nl-email'); return {valid: i.validity.valid, msg: i.validationMessage}; })()""")
    shot_emp = shot(page, "newsletter", "empty-required-validation")
    print("empty:", json.dumps(v_empty))
    if v_invalid["valid"] or not v_invalid["msg"]:
        append_finding(
            device="desktop", url=BASE, severity="HIGH",
            title="Newsletter accepts invalid email",
            actual=f"Submitting 'not-an-email' to the newsletter form resulted in validity={v_invalid['valid']} with message {v_invalid['msg']!r} — no error surfaced",
            expected="Newsletter form must reject malformed emails with a visible validation error",
            repro_steps="1. Load homepage\n2. In footer newsletter, type 'not-an-email'\n3. Click Subscribe",
            screenshot_path=shot_inv, affected_pages=[BASE],
        )
    else:
        print("newsletter invalid-email validation OK")
    if v_empty["valid"] or not v_empty["msg"]:
        append_finding(
            device="desktop", url=BASE, severity="HIGH",
            title="Newsletter accepts empty email",
            actual=f"Submitting an empty newsletter form resulted in validity={v_empty['valid']} — no required-field error",
            expected="Newsletter form must require an email address",
            repro_steps="1. Load homepage\n2. Click Subscribe with empty email",
            screenshot_path=shot_emp, affected_pages=[BASE],
        )
    else:
        print("newsletter empty validation OK")

    # ============ PHASE 4: STATS COUNTERS ============
    print("=== PHASE 4: STATS COUNTERS ===")
    reset_collectors()
    nav(page, BASE)
    labels = ["Clinics Listed", "Brands Listed", "Markets Covered", "Treatment Guides", "Metro Markets", "Years Independent"]
    counters_before = page.evaluate(COUNTER_SCRIPT, labels)
    try:
        page.get_by_text("Clinics Listed", exact=True).first.scroll_into_view_if_needed()
    except Exception:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(3000)
    counters_after = page.evaluate(COUNTER_SCRIPT, labels)
    print("counters before scroll:", json.dumps(counters_before, indent=1))
    print("counters after scroll+3s:", json.dumps(counters_after, indent=1))
    counter_html = page.evaluate("""(labels) => {
        const out = {};
        labels.forEach(l => {
            const el = Array.from(document.querySelectorAll('*')).find(e => (e.innerText||'').trim() === l);
            if (el && el.parentElement) out[l] = el.parentElement.outerHTML.slice(0, 400);
        });
        return out;
    }""", labels)
    shot_stats = shot(page, "stats", "counters-after-3s")
    nan_logs = [c for c in console_lines if "NaN" in c]
    print("NaN console lines:", json.dumps(nan_logs[:5]))
    still_zero = any(
        re.search(r"(^|\s)0\+($|\s)", v) or "0yrs" in v
        for v in counters_after.values()
    )
    if still_zero:
        append_finding(
            device="desktop", url=BASE, severity="MEDIUM",
            title="Stats counters render 0+ / 0yrs instead of live values",
            actual=f"After scrolling to the stats band and waiting 3s, counter values stayed at: {json.dumps(counters_after)}. Console shows count-up NaN logs: {json.dumps(nan_logs[:3])}. Static targets in the same section read 'LIVE 17,020+' and '10+'.",
            expected="Stats counters should animate/display their live target values (e.g. 17,020+ clinics, 10+ brands, 4 years)",
            repro_steps="1. Load homepage\n2. Scroll to the LIVE stats band\n3. Wait 3s and read the counter values",
            screenshot_path=shot_stats,
            notes="Root cause evidence: count-up animation logs 'NaN' (styled %c%d font-size:0 log) — the counter animation never resolves to its target, leaving the initial 0+/0yrs state rendered.",
            affected_pages=[BASE],
        )
    else:
        print("counters OK after scroll")

    # ============ PHASE 5: EMPTY STATE / DATA CONSISTENCY ============
    print("=== PHASE 5: EMPTY STATE / DATA CONSISTENCY ===")
    reset_collectors()
    nav(page, BASE)
    consistency = page.evaluate("""(() => {
        const b = document.body.innerText;
        const grab = (re) => { const m = b.match(re); return m ? m[0].replace(/\\n+/g,' ').slice(0,120) : null; };
        const featured = Array.from(document.querySelectorAll('[class*=featured] a, section a')).map(a => (a.innerText||'').trim().replace(/\\n+/g,' ')).filter(t => t && /clinic/i.test(t)).slice(0, 12);
        return {
            heroInjectors: grab(/\\d[\\d,.+]*\\s*VERIFIED INJECTORS/),
            liveClinics: grab(/LIVE\\s*[\\d,.+]+/),
            zeroClinics: grab(/\\d+ verified clinics/),
            noMatch: grab(/No verified clinics or injectors match[^\\n]*/),
            cities: grab(/License-verified providers in [^\\n]*/),
            featuredClinicCards: featured,
        };
    })()""")
    print(json.dumps(consistency, indent=1))
    shot_cons = shot(page, "empty-state", "data-consistency-fullpage")
    shot_clinics = None
    try:
        page.locator("section").filter(has_text="No verified clinics").first.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        shot_clinics = shot(page, "empty-state", "clinics-section-zero-and-test-data")
    except Exception:
        pass
    zero_claims = consistency.get("zeroClinics") or ""
    has_test_data = any(("Test Clinic" in c) or ("ABCD" in c) or ("Rishav" in c) for c in consistency.get("featuredClinicCards", []))
    if consistency.get("liveClinics") and zero_claims and consistency.get("noMatch"):
        append_finding(
            device="desktop", url=BASE, severity="CRITICAL",
            title="Homepage simultaneously claims 17,020+ verified clinics yet shows 0 results and test clinics",
            actual=("The homepage renders the stats-band headline %r alongside the clinics directory showing %r and %r. "
                    "The 'Featured Clinics' / 'TOP AESTHETIC CLINICS' section surfaces test fixtures including %r."
                    % (consistency.get("liveClinics"), consistency.get("zeroClinics"), consistency.get("noMatch"),
                       [c for c in consistency.get("featuredClinicCards", []) if "Test" in c or "ABCD" in c or "Rishav" in c][:3])),
            expected="Claims of verified clinics/injectors must match the directory data actually rendered; production must not display test fixtures as real clinics",
            repro_steps="1. Load homepage\n2. Read the LIVE stats band and hero claims\n3. Scroll to the clinics directory and Featured Clinics section",
            screenshot_path=shot_cons or "",
            notes="Medical-directory context: a user seeing '17,020+ verified clinics' + '12,400+ verified injectors' while the directory shows 0 results and test clinics ('Test Clinic', 'ABCD Clinic', 'Rishav's Clinic' in Houston, TX) is materially misleading.",
            affected_pages=[BASE, BASE + "/clinics", BASE + "/states"],
        )
        if shot_clinics:
            print("  clinics evidence shot:", shot_clinics)

    # ============ PHASE 6: /login + /list-your-practice ============
    print("=== PHASE 6: AUTH / LISTING PAGES ===")
    for path, scenario in [("/login", "login"), ("/list-your-practice", "list-your-practice")]:
        reset_collectors()
        resp = nav(page, BASE + path)
        status = resp.status if resp else None
        forms = page.locator("form").count()
        inputs = page.locator("form input, form textarea, form select").count()
        shot_p = shot(page, scenario, "page-load")
        print(f"{path}: status={status} forms={forms} inputs={inputs} title={page.title()[:60]!r} pageerrors={len(page_errors)}")
        if status != 200 or forms == 0:
            append_finding(
                device="desktop", url=BASE + path, severity="HIGH",
                title=f"{path} fails to load or has no form",
                actual=f"status={status}, forms={forms}, inputs={inputs}, console page errors: {page_errors[:3]}",
                expected=f"{path} should return 200 and render its form without JS errors",
                repro_steps=f"1. Navigate to {BASE + path}\n2. Observe page load and form rendering",
                screenshot_path=shot_p, affected_pages=[BASE + path],
            )
        else:
            print(f"{path} OK")

    # ============ PHASE 7: BACK / FORWARD ============
    print("=== PHASE 7: BACK/FORWARD ===")
    reset_collectors()
    nav(page, BASE)
    home_title = page.title()
    f = hero_form(page)
    f.locator("input").first.fill("Botox")
    f.get_by_role("button", name="Search").click()
    page.wait_for_timeout(4500)
    search_url = page.url
    page.go_back()
    page.wait_for_timeout(3500)
    back_url = page.url
    back_title = page.title()
    hero_visible = page.get_by_text("Find Your Injector.").count() > 0
    print(f"back: url={back_url} title={back_title!r} hero_visible={hero_visible}")
    shot_back = shot(page, "back-forward", "after-back-homepage")
    if back_url != BASE or not hero_visible:
        append_finding(
            device="desktop", url=BASE, severity="HIGH",
            title="Back navigation does not restore the homepage",
            actual=f"After navigating homepage -> search results -> back, URL={back_url} title={back_title!r} hero rendered={hero_visible}",
            expected="Browser back from search results should restore the homepage with content",
            repro_steps="1. Load homepage\n2. Search 'Botox'\n3. Press browser back",
            screenshot_path=shot_back, affected_pages=[BASE, search_url],
        )
    else:
        print("back OK")
    page.go_forward()
    page.wait_for_timeout(3500)
    fwd_url = page.url
    print(f"forward: url={fwd_url}")
    if fwd_url != search_url:
        append_finding(
            device="desktop", url=search_url, severity="MEDIUM",
            title="Forward navigation does not restore search results",
            actual=f"After homepage -> search -> back -> forward, URL={fwd_url} expected {search_url}",
            expected="Browser forward should restore the search results page",
            repro_steps="1. Load homepage\n2. Search 'Botox'\n3. Back, then Forward",
            screenshot_path=shot(page, "back-forward", "after-forward-search"), affected_pages=[BASE, search_url],
        )
    else:
        print("forward OK")

    browser.close()

print("=== FINAL SUMMARY ===")
with open(ROOT / "data" / "findings.json") as fh:
    all_findings = json.load(fh)
desktop_findings = [x for x in all_findings if x.get("device") == "desktop"]
missing_shot = [x for x in desktop_findings if not x.get("screenshot_path") or not (ROOT / x["screenshot_path"]).exists()]
print(f"total findings: {len(all_findings)} | desktop: {len(desktop_findings)} | missing screenshots: {len(missing_shot)}")
for x in desktop_findings:
    print(f"  {x['severity']:<8} {x['title'][:80]}")
