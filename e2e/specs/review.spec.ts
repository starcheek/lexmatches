// Screenshot tour of the non-reader screens at desktop and phone width. No translation cost.
// Run: sh e2e/run.sh review.spec.ts   -> e2e/screenshots/review/<tag>-*.png
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { removeSampleBooks } from "./sample";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.resolve(here, "../screenshots/review");
const TEXT = `Le premier soir je me suis donc endormi sur le sable à mille milles de toute terre habitée.

Alors vous imaginez ma surprise, au lever du jour, quand une drôle de petite voix m'a réveillé.`;

const tour = async (page: Page, tag: string) => {
  const shot = (name: string) => page.screenshot({ path: path.join(dir, `${tag}-${name}.png`), fullPage: true });
  await page.addInitScript(() => localStorage.setItem("lexmatches:reader-intro:v1", "1")); // help already seen
  await page.goto("/");
  await shot("01-landing");
  await page.goto("/auth");
  await shot("02-auth");
  await page.getByRole("tab", { name: "Sign Up" }).click();
  await page.locator("#signup-email").fill(`review-${tag}-${Date.now()}@example.com`);
  await page.locator("#signup-password").fill("review-password-123");
  await page.getByRole("button", { name: "Create Account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByTestId("book-card")).toHaveCount(1);
  await shot("03-dashboard-sample");
  await removeSampleBooks(page);
  await shot("03-dashboard-empty");
  await page.getByRole("button", { name: /Paste Text/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#text-title").fill("Le petit prince (review)");
  await dialog.locator("#pasted-text").fill(TEXT);
  await page.waitForTimeout(400);
  await shot("04-paste-dialog");
  await dialog.getByRole("button", { name: "Add text" }).click();
  await expect(page).toHaveURL(/\/read\//);
  await expect(page.locator("[data-sentence]").first()).toBeVisible();
  await shot("05-reader-untranslated");
  await page.getByRole("button", { name: "Search in book" }).click();
  await page.getByLabel("Search text").fill("sable");
  await expect(page.getByRole("listitem").first()).toBeVisible();
  await shot("06-search");
  await page.keyboard.press("Escape");
  await page.goto("/dashboard");
  await expect(page.getByTestId("book-card")).toHaveCount(1);
  await shot("07-dashboard-book");
  await page.goto("/progress");
  await page.waitForTimeout(800);
  await shot("08-progress");
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await shot("09-settings");
};

test("review tour desktop", async ({ page }) => {
  await tour(page, "desktop");
});

test("review tour mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await tour(page, "mobile");
});
