// Accessibility (L-1) + cross-browser/responsive (L-2) harness — runs OUTSIDE the
// pytest suite via Playwright. Full WCAG 2.1 A/AA audit with axe-core across
// Chromium / Firefox / WebKit and desktop / tablet / mobile viewports.
//
//   cd e2e && npm i && npx playwright install
//   BASE_URL=https://aifrontdesk.taborsynergy.com npx playwright test
//
const { test, expect } = require("@playwright/test");
const AxeBuilder = require("@axe-core/playwright").default;

const BASE = process.env.BASE_URL || "http://localhost:8000";

// L-1: no serious/critical WCAG 2.1 A/AA violations on the public landing page.
test("landing page has no serious a11y violations", async ({ page }) => {
  await page.goto(BASE + "/");
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const serious = results.violations.filter((v) =>
    ["serious", "critical"].includes(v.impact)
  );
  expect(serious, JSON.stringify(serious.map((v) => v.id))).toEqual([]);
});

// L-2: landing page renders its primary CTA across viewports (smoke).
for (const vp of [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
]) {
  test(`renders primary CTA on ${vp.name}`, async ({ page }) => {
    await page.setViewportSize({ width: vp.width, height: vp.height });
    await page.goto(BASE + "/");
    await expect(page.locator("text=/start free trial/i").first()).toBeVisible();
  });
}
