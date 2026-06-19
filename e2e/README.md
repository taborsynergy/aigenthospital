# E2E: Accessibility (L-1) + Cross-browser/Device (L-2)

These run **outside** the Python/pytest suite — they need a real browser engine.
The pytest suite keeps cheap static guards (`backend/tests/test_frontend_a11y.py`);
this harness does the full axe-core WCAG audit and the multi-browser/viewport matrix.

## Run
```bash
cd e2e
npm install
npx playwright install            # download Chromium / Firefox / WebKit
BASE_URL=https://aifrontdesk.taborsynergy.com npx playwright test
```

## What it covers
- **L-1 Accessibility** — `a11y.spec.js` runs axe-core (WCAG 2.1 A/AA) on the
  landing page and fails on any `serious`/`critical` violation.
- **L-2 Cross-browser/device** — `playwright.config.js` runs every spec across
  Chromium, Firefox, WebKit (Safari engine), plus Pixel 7 and iPhone 14 emulation;
  the viewport smoke checks the primary CTA renders on mobile/tablet/desktop.

## Notes
- For a full real-device matrix (actual iOS/Android Safari, older browsers), point
  Playwright at **BrowserStack** via its SDK, or run `@axe-core/cli` in CI.
- The CSP on the production site allows `cdn.jsdelivr.net` scripts, so axe can also
  be run ad-hoc from the browser console against the live site.
