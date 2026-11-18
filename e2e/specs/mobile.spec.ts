import { devices, expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { removeSampleBooks } from "./sample";

// Phone reader: the floating translations button follows the thumb (side and height of the scroll
// gestures) and turns the whole page's glosses on and off. Translations come from the gloss fixture
// (patched pages response), so this costs nothing.

const here = path.dirname(fileURLToPath(import.meta.url));
const shots = path.resolve(here, "../screenshots");
const fixture = JSON.parse(fs.readFileSync(path.resolve(here, "../fixtures/gloss_verne.json"), "utf8"));
const { defaultBrowserType: _, ...phone } = devices["Pixel 7"];
test.use(phone);

/** A real one-finger vertical swipe (Chrome DevTools touch input), so the page scrolls as on a phone. */
async function swipe(page: Page, x: number, fromY: number, toY: number) {
  const cdp = await page.context().newCDPSession(page);
  const steps = 8;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y: fromY }] });
  for (let i = 1; i <= steps; i++) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: fromY + ((toY - fromY) * i) / steps }] });
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await cdp.detach();
}

test("phone: thumb button follows the scrolling hand and toggles the page's glosses", async ({ page }) => {
  await page.route(/\/api\/books\/[^/]+\/pages(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const pages = await response.json();
    for (const p of pages) Object.assign(p, { translated_data: fixture.translated_data, status: "completed" });
    await route.fulfill({ response, json: pages });
  });
  await page.addInitScript(() => localStorage.setItem("lexmatches:reader-intro:v1", "1"));

  await page.goto("/auth");
  await page.getByRole("tab", { name: "Sign Up" }).click();
  await page.locator("#signup-email").fill(`e2e-mobile-${Date.now()}@example.com`);
  await page.locator("#signup-password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create Account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await removeSampleBooks(page);
  await page.getByRole("button", { name: /Paste Text/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#text-title").fill("Mobile e2e");
  await dialog.locator("#pasted-text").fill(fixture.text.slice(0, 1500));
  await dialog.getByRole("button", { name: "Add text" }).click();
  await expect(page).toHaveURL(/\/read\//);
  await expect(page.locator(".chunk").first()).toBeVisible();

  const button = page.getByTestId("thumb-toggle");
  const view = page.viewportSize()!;
  // no thumb data yet: right-handed default; line mode is not offered on touch
  await expect(button).toHaveAttribute("data-side", "right");
  await expect(page.getByRole("button", { name: "Line", exact: true })).toHaveCount(0);
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(0);

  // one tap: every gloss of the page; again: none
  await button.tap();
  await expect(button).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".chunk-gloss").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Glosses" })).toHaveAttribute("aria-pressed", "true"); // dock in step
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(shots, "50-mobile-glosses-on.png") });
  await button.tap();
  await expect(button).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(0);

  // scrolling with the left thumb, high on the screen: the button moves to the left, to that height
  const y0 = await page.evaluate(() => window.scrollY);
  for (let i = 0; i < 4; i++) {
    await swipe(page, 70, 340, 200);
    await swipe(page, 70, 200, 300);
  }
  expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(y0); // the swipes really scrolled
  await expect(button).toHaveAttribute("data-side", "left");
  await page.waitForTimeout(400); // the move is animated
  const box = (await button.boundingBox())!;
  expect(box.x).toBeLessThan(view.width / 2);
  expect(Math.abs(box.y + box.height / 2 - 268)).toBeLessThan(40); // about the average height of the swipes
  await page.screenshot({ path: path.join(shots, "51-mobile-left-thumb.png") });

  // remembered on the next visit; right-hand scrolling brings it back
  await page.reload();
  await expect(page.locator(".chunk").first()).toBeVisible();
  await expect(button).toHaveAttribute("data-side", "left");
  for (let i = 0; i < 6; i++) await swipe(page, view.width - 60, 600, 450);
  await expect(button).toHaveAttribute("data-side", "right");
});
