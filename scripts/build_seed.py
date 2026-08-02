#!/usr/bin/env python3
"""Build the crawl seed list for https://www.injector.world/.

Regenerable: rerun to rebuild `data/seed-urls.json`.

Sources & deterministic rules
-----------------------------
1. STATIC (all, no cap): every URL from `/sitemaps/pages` (16 URLs).
2. NAV/FOOTER (no cap): explicit top-level routes verified from the
   homepage HTML: /login, /list-your-practice, /search, /states. These are
   whitelisted explicitly (they do not appear in any sitemap).
3. GUIDES (cap 10): first N from `/sitemaps/guides` in sitemap order.
4. NEWS (cap 10): first N from `/sitemaps/news` in sitemap order.
5. BRANDS (cap 10): first N `/brands/<brand>` pages from the homepage nav
   (not present in sitemaps; homepage links 9 brand pages).
6. SERVICES (cap 10): first N `/services/<service>` pages from the
   homepage nav (sitemap only has `/services/<service>/<state>/<city>`
   combos, so standalone service pages come from the homepage).
7. STATE/CITY (cap 10): homepage-nav state/city links first (e.g.
   /california, /california/los-angeles-ca, /texas), then top up from
   `/sitemaps/auto` in sitemap order.
   `/sitemaps/clinics` was observed EMPTY (2026-08-01): if still empty,
   clinic detail URLs are skipped and left for in-page discovery.

If the deduped total is below 60, top up with more state/city pages from
`/sitemaps/auto` until we reach 60.

Exclusions: /admin/, /api/, /_next/, /search?* (search route with query
params is covered by UI tests, not crawling).

Only the Python stdlib is required (urllib + xml.etree).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

SITE = "https://www.injector.world"
SITEMAP_INDEX = f"{SITE}/sitemap.xml"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) injector.world QA-SeedBuilder/1.0"
SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

US_STATE_SLUGS = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "district-of-columbia", "florida", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new-hampshire", "new-jersey", "new-mexico", "new-york",
    "north-carolina", "north-dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode-island", "south-carolina", "south-dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west-virginia", "wisconsin", "wyoming",
}

# Deterministic caps per dynamic category.
CAP = {
    "guides": 10,
    "news": 10,
    "brands": 10,
    "services": 10,
    "state_city": 10,
}

MIN_URLS = 60
MAX_URLS = 100

# Top-level nav/footer routes that are NOT in any sitemap but verified on
# the homepage. /list-your-practice and /states are also in /sitemaps/pages;
# dedupe handles that.
NAV_FOOTER = ["/login", "/list-your-practice", "/search", "/states"]

EXCLUDED_PREFIXES = ("/admin/", "/api/", "/_next/", "/search?")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def parse_locs(body: bytes) -> list[str]:
    """Parse <loc> entries from a sitemap index or urlset (either ns form)."""
    root = ET.fromstring(body)
    locs = [el.text for el in root.iter(f"{SM_NS}loc")]
    return [loc for loc in locs if loc]


def try_fetch_sitemap(path: str) -> list[str] | None:
    """Fetch a sub-sitemap; try bare path first, then with .xml appended."""
    candidates = [path, f"{path}.xml"] if not path.endswith(".xml") else [path]
    for cand in candidates:
        try:
            return parse_locs(fetch(cand))
        except Exception as exc:  # noqa: BLE001 - try next candidate
            print(f"  [warn] failed {cand}: {exc!r}", file=sys.stderr)
    return None


def fetch_sitemap_index() -> list[str]:
    locs = parse_locs(fetch(SITEMAP_INDEX))
    if not locs:
        raise RuntimeError(f"sitemap index returned no <loc>: {SITEMAP_INDEX}")
    return locs


def fetch_homepage_hrefs() -> set[str]:
    html = fetch(f"{SITE}/").decode("utf-8", "replace")
    return set(re.findall(r'href="(/[^"]+)"', html))


def state_city_sort_key(path: str) -> tuple[int, str]:
    """Ordering for /state and /state/city pages: single-seg first, then city."""
    segs = [s for s in path.split("/") if s]
    return (len(segs), path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / "data" / "seed-urls.json"),
        help="Output JSON path (default: data/seed-urls.json)",
    )
    args = ap.parse_args()

    print("Fetching sitemap index...")
    sub_locs = fetch_sitemap_index()
    print(f"  found {len(sub_locs)} sub-sitemap locs")
    for l in sub_locs:
        print(f"    {l}")

    pools: dict[str, list[str]] = {}
    for loc in sub_locs:
        name = urlparse(loc).path.rstrip("/").split("/")[-1]
        print(f"Fetching sub-sitemap: {name} ({loc})")
        try:
            locs = try_fetch_sitemap(loc)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {name}: {exc!r}", file=sys.stderr)
            locs = None
        pools[name] = locs or []
        print(f"  {name}: {len(pools[name])} URLs")

    print("Fetching homepage to discover nav/footer links...")
    homepage_hrefs = fetch_homepage_hrefs()
    brand_hrefs = sorted(
        h for h in homepage_hrefs if h.startswith("/brands/") and h.count("/") == 2
    )
    service_hrefs = sorted(
        h for h in homepage_hrefs if h.startswith("/services/") and h.count("/") == 2
    )
    state_city_hrefs = sorted(
        h
        for h in homepage_hrefs
        if (seg := h.strip("/").split("/"))[0] in US_STATE_SLUGS and len(seg) <= 2
    )
    print(f"  homepage /brands/* pages: {len(brand_hrefs)}")
    print(f"  homepage /services/* pages: {len(service_hrefs)}")
    print(f"  homepage state/city links: {len(state_city_hrefs)}")

    seed: list[str] = []
    counts: dict[str, int] = {}

    def add(category: str, urls: list[str], cap: int | None = None) -> None:
        for u in urls:
            if u in seed:
                continue
            if u.startswith(EXCLUDED_PREFIXES):
                continue
            seed.append(u)
            counts[category] = counts.get(category, 0) + 1
            if cap is not None and counts[category] >= cap:
                break

    # 1. static pages - all
    add("static", pools.get("pages", []))
    # 2. nav/footer
    add("nav_footer", [f"{SITE}{p}" for p in NAV_FOOTER])
    # 3-4. guides, news - capped samples
    add("guides", pools.get("guides", []), CAP["guides"])
    add("news", pools.get("news", []), CAP["news"])
    # 5. brands - homepage-only
    add("brands", [f"{SITE}{p}" for p in brand_hrefs], CAP["brands"])
    # 6. services - homepage-only
    add("services", [f"{SITE}{p}" for p in service_hrefs], CAP["services"])
    # 7. state/city from homepage nav first, then top up from /sitemaps/auto
    #    (homepage links e.g. /california, /california/los-angeles-ca, /texas)
    state_city_pool = sorted(pools.get("auto", []), key=state_city_sort_key)
    state_city_ordered = [f"{SITE}{p}" for p in state_city_hrefs] + [
        u for u in state_city_pool if f"{SITE}{u}" not in {f"{SITE}{p}" for p in state_city_hrefs}
    ]
    add("state_city", state_city_ordered, CAP["state_city"])

    # Top-up: if still under MIN_URLS, pull more state/city pages from auto.
    topup = 0
    if len(seed) < MIN_URLS and pools.get("auto"):
        for u in state_city_pool:
            if len(seed) >= MIN_URLS:
                break
            if u in seed:
                continue
            seed.append(u)
            counts["state_city_topup"] = counts.get("state_city_topup", 0) + 1
            topup += 1

    # Guards
    bad = [u for u in seed if u.startswith(EXCLUDED_PREFIXES)]
    if bad:
        print(f"FATAL: forbidden URLs in seed: {bad}", file=sys.stderr)
        return 1
    if not MIN_URLS <= len(seed) <= MAX_URLS:
        print(
            f"FATAL: seed count {len(seed)} outside [{MIN_URLS}, {MAX_URLS}]",
            file=sys.stderr,
        )
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

    print("\n=== SEED SUMMARY ===")
    print(f"total seed URLs: {len(seed)} (target {MIN_URLS}-{MAX_URLS})")
    for cat, n in sorted(counts.items()):
        print(f"  {cat:16s}: {n}")
    if topup:
        print(f"  state_city_topup : {topup} (added to reach {MIN_URLS})")
    # Per-category cap check
    for cat, cap in CAP.items():
        got = counts.get(cat, 0)
        status = "OK" if got <= cap else "OVER-CAP"
        print(f"  cap[{cat:10s}] = {got:3d} / {cap}  {status}")
        if got > cap:
            print(f"FATAL: category {cat} exceeds cap {cap}", file=sys.stderr)
            return 1
    print(f"wrote: {out}")

    # sanity: count top-level distinct path segments for visibility
    segs: dict[str, int] = {}
    for u in seed:
        seg = urlparse(u).path.split("/")[1] if urlparse(u).path != "/" else "(root)"
        segs[seg] = segs.get(seg, 0) + 1
    print("  top-level coverage:", dict(sorted(segs.items(), key=lambda kv: -kv[1])))

    return 0


if __name__ == "__main__":
    sys.exit(main())
