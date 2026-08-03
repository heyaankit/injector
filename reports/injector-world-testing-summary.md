# injector.world QA Testing Campaign Summary

**1-2 August 2026 | Independent QA audit**

| Field | Value |
|---|---|
| Site under test | https://www.injector.world/ |
| Engagement | Independent, read-only QA audit of the live site |
| Campaign dates | 1-2 August 2026 |
| Tester | Independent QA team |

## 1. Executive Overview

An independent, non-destructive QA audit of https://www.injector.world/, the aesthetic-injector directory behind the tagline "Find Your Injector." The campaign ran 1-2 August 2026 across desktop and mobile browsers, produced two severity-ranked DOCX bug reports, and recorded 201 page and device checks yielding 70 findings. Testing was read-only against the production site: no data was written, no forms were submitted with real values, and no internal areas were accessed.

## 2. Scope & Test Coverage

- 67 unique URLs x 3 device contexts = 201 crawl records. Every requested page loaded and was measured: 0 failed crawls and 0 pages blocked by bot protection.
- Seed list built from the sitemap index plus the homepage navigation: 16 static pages, login and search routes, 10 guides, 10 news articles, 9 brand pages, 10 service pages, and 10 state and city samples.
- Device contexts: desktop Chromium at 1920x1080 with responsive widths 1366, 1024, and 768; mobile emulation of an iPhone 13 (390x664, 3x scale) and a Pixel 7 (412x839, 2.625x scale).
- Dynamic sections (guides, news, brands, services, state and city listings) were sampled with capped, deterministic selection so the crawl stays reproducible without scanning the full site.

The site is a Next.js (App Router) application. The crawl used its sitemap index (pages, guides, news, and an auto-generated listing sitemap) as the discovery source, then appended navigation and footer routes that the sitemaps do not list.

## 3. Methodology & Toolchain

| Tool | Purpose |
|---|---|
| Playwright 1.62.0 (Python 3.14.6) | Headless Chromium automation: navigation, interaction, and measurement |
| Desktop profile | Chromium at 1920x1080; responsive re-tests at 1366, 1024, and 768 |
| Mobile profiles | Playwright emulation: iPhone 13 and Pixel 7 viewports and touch behavior |
| python-docx 1.2.0 | DOCX report generation with color-coded severity and embedded screenshots |
| LibreOffice (headless) | Render validation of every report via PDF conversion |

- Navigation strategy: pages load to domcontentloaded plus a capped networkidle window, with a short settle delay before measurement. This matches the Next.js behavior of the site.
- Test types: visual, functional and logical, responsive, basic accessibility, and performance. Performance used a throttled Slow 4G profile with 4x CPU on desktop, plus mobile load-time baselines for comparison.
- Non-destructive by design: newsletter and search forms were exercised with invalid or empty input only; no requests to /admin/ or /api/; no bot-protection bypass; no Lighthouse runs.

## 4. Phases Performed

- **Environment setup and smoke test.** Browser stack, navigation timing, and screenshot pipeline verified against the live site.
- **Site inventory and seed list.** A 67-URL crawl list assembled from the sitemap index and homepage navigation.
- **Crawl and evidence harness.** A read-only crawler that captures screenshots, load times, console errors, and broken-image data for every page and device.
- **Severity rubric and report builder.** A CRITICAL to LOW classification rubric with a color-coded DOCX report generator.
- **Desktop deep crawl.** Full crawl of all 67 URLs on Chromium, plus visual, functional, responsive (4 widths), accessibility, and performance passes.
- **Mobile deep crawl.** The same 67 URLs on iPhone 13 and Pixel 7 emulation, with visual, functional, and performance passes.
- **Report generation.** Both DOCX bug reports built from the consolidated findings, one per platform.
- **Validation suite.** A six-check gate over both reports covering structure, rendering, evidence, placeholders, duplicates, and coverage.
- **Live re-verification.** 20% of the reported issues re-tested against the production site with fresh evidence.

## 5. Findings Summary

70 findings were filed across both platforms (49 on desktop, 21 on mobile). The severity distribution below reflects the full dataset. The two CRITICAL findings are the same homepage claim recorded independently on desktop and mobile.

| Severity | Count |
|---|---|
| CRITICAL | 2 |
| HIGH | 18 |
| MEDIUM | 27 |
| LOW | 23 |
| **Total** | **70** |

Headline findings:

- **CRITICAL: Directory claim vs. reality.** The homepage advertises "17,020+ clinics" and "12,400+ verified injectors" while the clinics directory renders "No verified clinics or injectors match." for the same data.
- **HIGH: 12 broken navigation links.** Nine /guides/* URLs and three /services/* URLs linked from the header and footer return HTTP 404.
- **HIGH: Site-wide search returns 0 results.** A search for "Botox" returns 0 results on both desktop and mobile.
- **HIGH: Mobile hamburger menu overlaps.** In the mobile menu, treatment links are covered by overlapping panel content, so a tap lands on the wrong element and the menu stays open.
- **MEDIUM: Accessibility, tap targets, and content.** Newsletter inputs lack accessible labels, mobile menu links have 18px tap targets (below the 44px WCAG 2.5.8 minimum), several pages show broken images, and the /news page logs console errors.

The homepage statistics counters (17,020+, 12,400+) were also investigated. They work correctly: they are a scroll-triggered count-up animation, so the zero state seen before scrolling is expected behavior, not a bug.

## 6. Quality Assurance & Validation

- **Six-check validation gate.** Both reports pass a scripted gate covering python-docx reopen, LibreOffice PDF render, embedded screenshot count, zero placeholder text, duplicate detection, and a crawl-manifest cross-check. Result: all checks passed, exit code 0.
- **20% live re-verification.** 10 issues were sampled across both reports (22.7%, above the 20% gate), covering all four severity buckets. 9 reproduced live against the production site; 1 did not (mobile footer tap interception) and was moved to the "Verified: Not Reproducible" section.
- **Evidence for every issue.** Each reported issue carries at least one embedded screenshot captured during the crawl, with a file-level caption and a verifiable path in the evidence library.
- **Conservative testing.** Bot protection was detected and recorded, never bypassed. Only invalid and empty input was used on forms, and no internal routes were requested.

## 7. Deliverables

| Artifact | Description |
|---|---|
| reports/injector-world-desktop-bug-report.docx | 35 issues (1 CRITICAL, 13 HIGH, 20 MEDIUM, 1 LOW), a "Verified: Not Reproducible" section (3 items), a performance appendix (11 load-time entries), and a coverage table (67 pages) |
| reports/injector-world-mobile-bug-report.docx | 8 issues (1 CRITICAL, 2 HIGH, 5 MEDIUM), a "Verified: Not Reproducible" section (7 items), a performance appendix (5 entries), and a coverage table (134 mobile pages) |
| data/findings.json | 70 machine-readable findings (49 desktop, 21 mobile) with severity, steps, expected vs. actual, and screenshot paths |
| data/crawl-manifest.json | 201 crawl records (67 URLs x 3 device contexts) with load times, console errors, and status per page |
| data/seed-urls.json | The 67-URL seed list used for the crawl |
| evidence/ | Screenshot library per device and page, plus re-verification captures. Regenerable at any time via the harness |
| scripts/ | Crawl harness, report builder, severity rubric, validation gate, and pinned requirements (playwright 1.62.0, python-docx 1.2.0) |

Each bug report contains an executive summary, a severity summary table, issues ordered CRITICAL to LOW with color-coded severity headings, steps to reproduce, expected vs. actual behavior, and embedded screenshot evidence. The machine-readable findings and manifest files allow the reports to be rebuilt and re-checked at any time.

## 8. Reproducibility

The audit is fully regenerable from the repository. After installing the pinned dependencies, re-run the crawl per device profile, rebuild each report from data/findings.json, and run the validation gate:

1. `pip install -r scripts/requirements.txt` - Install pinned dependencies
2. `python scripts/harness.py desktop` - Crawl the desktop profile (67 pages)
3. `python scripts/harness.py iphone-13` - Crawl iPhone 13 emulation (67 pages)
4. `python scripts/harness.py pixel-7` - Crawl Pixel 7 emulation (67 pages)
5. `python scripts/report_builder.py --device desktop --out <docx> --as-of <ISO>` - Regenerate the desktop report
6. `python scripts/report_builder.py --device mobile --out <docx> --as-of <ISO>` - Regenerate the mobile report
7. `python scripts/validate_reports.py` - Run the six-check validation gate
