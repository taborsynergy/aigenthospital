// Playwright config for the a11y + cross-browser harness (L-1 / L-2).
const { devices } = require("@playwright/test");

module.exports = {
  testDir: ".",
  timeout: 60_000,
  reporter: [["list"], ["html", { open: "never" }]],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox",  use: { ...devices["Desktop Firefox"] } },
    { name: "webkit",   use: { ...devices["Desktop Safari"] } },  // Safari engine
    { name: "mobile-chrome", use: { ...devices["Pixel 7"] } },
    { name: "mobile-safari", use: { ...devices["iPhone 14"] } },
  ],
};
