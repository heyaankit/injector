# injector.world: Professional QA Test Reports

An independent QA testing campaign of the live aesthetic-injector directory at https://www.injector.world/ ("Find Your Injector."). This repo contains the findings, evidence, and two severity-ranked DOCX bug reports produced by the audit.

## What this is

A software-tester style QA audit combining visual and logical checks, executed with Playwright (Python) against the production Next.js (App Router) site. The campaign covered desktop (Chromium at 1920x1080, plus responsive widths 1366, 1024, and 768) and two mobile profiles (iPhone 13 and Pixel 7 emulation), producing two DOCX bug reports with screenshot evidence for every issue.

All testing was read-only against the public site, and the campaign ran August 1-2, 2026.

## Headline findings

- **CRITICAL: Directory claim vs. reality mismatch.** The homepage advertises "17,020+ clinics" and "12,400+ verified injectors" while the clinics directory renders "No verified clinics or injectors match." for the same data.
- **HIGH: 12 broken navigation links.** Nine `/guides/*` URLs and three `/services/*` URLs linked from the header and footer return HTTP 404.
- **HIGH: Site-wide search returns 0 results.** A search for "Botox" returns 0 results on both desktop and mobile.
- **HIGH (mobile): Hamburger menu treatment links don't navigate.** In the mobile menu, treatment links are covered by overlapping panel content, so a tap lands on the wrong element and the menu stays open.
- **MEDIUM: Accessibility and content issues.** Newsletter inputs lack accessible labels, mobile menu links have 18px tap targets (below the 44px WCAG 2.5.8 minimum), several pages have broken images, and the `/news` page logs console errors.

Note: the homepage stats counters (17,020+, 12,400+) were investigated and work correctly. They are a scroll-triggered count-up animation, not a bug.

## Deliverables

| Artifact | Contents |
|---|---|
| `reports/injector-world-desktop-bug-report.docx` | 35 issues (1 CRITICAL, 13 HIGH, 20 MEDIUM, 1 LOW), a "Verified: Not Reproducible" section, a performance appendix, and a coverage section (67 pages) |
| `reports/injector-world-mobile-bug-report.docx` | 8 issues (1 CRITICAL, 2 HIGH, 5 MEDIUM), a "Verified: Not Reproducible" section (7 items), a performance appendix, and a coverage section (134 pages) |
| `data/findings.json` | 70 machine-readable findings (49 desktop, 21 mobile) |
| `data/crawl-manifest.json` | 201 audited pages (67 URLs, each under desktop, iPhone 13, and Pixel 7), 0 failed crawls |
| `data/seed-urls.json` | The 67-URL seed list used for the crawl |
| `evidence/` | Screenshot evidence per device and page. Gitignored and regenerable via the harness |

Each DOCX report contains an executive summary, a severity summary table, issues ordered CRITICAL to LOW with color-coded severity, steps to reproduce, expected vs. actual behavior, and embedded screenshot evidence.

## Repo layout

```
scripts/
  harness.py          Playwright crawl harness: screenshots, load timing, findings + manifest recording
  report_builder.py   DOCX bug report generator (python-docx)
  rubric.py           Single source of truth for severity colors and ordering
  validate_reports.py 6-check validation gate for both reports
  build_seed.py       Generates the 67-URL seed list
  smoke_test.py       Environment smoke test
  ux_rubric.py        Single source of truth for the 17 UX areas, 4 severity tiers, and /10 score
  ux_harness.py       Interaction-capable UX crawl harness: probes + discovery pass
  validate_ux_reports.py  6-check validation gate for the UX audit artifacts
  requirements.txt    Pinned dependencies (playwright 1.62.0, python-docx 1.2.0)
data/
  findings.json       All 70 findings, severity-ranked
  crawl-manifest.json Crawl results for all 201 page/device combinations
  crawl-manifest-schema.json
  seed-urls.json      67-URL seed list
reports/
  injector-world-desktop-bug-report.docx
  injector-world-mobile-bug-report.docx
```

## How it was tested

The audit is reproducible:

1. Install dependencies: `pip install -r scripts/requirements.txt`
2. Crawl a device profile: `python scripts/harness.py desktop|iphone-13|pixel-7`
   The harness walks the seed list, captures full-page and viewport screenshots, records load times, console errors, broken images, and bot-protection signals, and appends results to `data/findings.json` and `data/crawl-manifest.json`.
3. Regenerate a report: `python scripts/report_builder.py --device mobile|desktop --out <docx> --as-of <ISO>`
   Reports are device-filtered and rebuilt from `data/findings.json`.
4. Validate: `python scripts/validate_reports.py`
   Runs six checks against both reports and exits 0 with "ALL CHECKS PASSED".

The crawl is conservative by design: pages load to `domcontentloaded` plus a capped `networkidle`, with a settle delay before measurement. Bot protection is detected and recorded, never bypassed.

## UI/UX audit

On top of the QA bug campaign, a dedicated UI/UX audit was completed against the same live site. It evaluates the experience across **17 UX areas** (navigation, forms, buttons, scrolling, hover states, and more) and classifies each finding into one of **4 severity tiers**: Critical, Most Important, Important, and Normal. The audit produces a **/10 UX quality score** per device and overall.

Coverage mirrors the QA campaign: desktop (Chromium at 1920x1080, plus responsive widths 1366, 1024, and 768) and two mobile profiles (iPhone 13 and Pixel 7 emulation). Unlike a passive crawl, the UX harness runs **interaction probes** against menus, forms, buttons, scrolling, and hover states, and includes a **discovery pass** that samples internal links to surface reachable pages not yet in the coverage list.

The UX audit is fully reproducible with the scripts below.

## How to run the UX audit

The UX audit is reproducible end-to-end:

1. Install dependencies: `pip install -r scripts/requirements.txt`
2. Run the desktop crawl: `python3 scripts/ux_harness.py desktop`
   Crawls the desktop profile with base crawl plus interaction probes, writing to `evidence/ux/` and `data/ux-manifest.json`.
3. Run the mobile crawls: `python3 scripts/ux_harness.py iphone-13` and `python3 scripts/ux_harness.py pixel-7`
   Same crawl and probes under each mobile emulation profile.
4. Run the discovery pass: `python3 scripts/ux_harness.py desktop --discover`
   Collects internal links across crawled pages, diffs them against `data/ux-coverage.json`, and records the bounded delta.
5. Validate the audit artifacts: `python3 scripts/validate_ux_reports.py`
   Runs six checks (schema, format, coverage, dedup, score, render) and exits 0 with "ALL CHECKS PASSED".

The harness is non-destructive by design: forms receive invalid or empty data only, bot protection is detected and recorded but never bypassed, and a single failed page never aborts the run.

## Quality gates passed

- **20% live re-verification.** 10 issues were sampled across both reports (22.7%, above the 20% gate), covering all four severity buckets. 9 reproduced live; 1 (mobile footer tap interception) was not reproducible and was moved to the "Verified: Not Reproducible" section.
- **Render check.** Both DOCX reports render cleanly via LibreOffice headless (PDF conversion exits 0).
- **Zero placeholders.** No TBD, `[insert]`, TODO, or lorem text in either report, checked across paragraphs, tables, and raw document XML.
- **Non-destructive compliance.** No real form submissions or newsletter signups (only invalid and empty input was used), no requests to `/admin/` or `/api/`, no bot-protection bypass, and no Lighthouse runs.

## Note on evidence/

The `evidence/` directory is 628 MB of crawl screenshots and is excluded via `.gitignore` to respect GitHub repository size limits. The DOCX reports embed the key screenshots, and the directory can be regenerated at any time by re-running the harness.
