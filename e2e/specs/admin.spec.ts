import { expect, test } from "@playwright/test";

// Needs the server's ADMIN_TOKEN:  ADMIN_TOKEN=... sh e2e/run.sh admin
const token = process.env.ADMIN_TOKEN ?? "";

test("admin: create a test account, sign in with it, close sign-up, delete the account", async ({ page, browser }) => {
  test.skip(!token, "ADMIN_TOKEN not set");
  const email = `e2e-tester-${Date.now()}@example.com`;

  await page.goto(`/admin#${token}`);
  await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible();
  expect(page.url()).not.toContain(token); // the token leaves the address bar

  await page.locator("#new-email").fill(email);
  await page.getByRole("button", { name: "Create account" }).click();
  const password = await page.getByTestId("issued-password").innerText();
  expect(password.length).toBeGreaterThanOrEqual(8);
  await expect(page.getByRole("cell", { name: email, exact: true })).toBeVisible();

  // sign-up closed: a stranger is refused, the issued account still signs in
  const wasOpen = await page.getByTestId("signup-switch").innerText();
  if (wasOpen === "Close sign-up") await page.getByTestId("signup-switch").click();
  await expect(page.getByTestId("signup-switch")).toHaveText("Open sign-up");
  await page.screenshot({ path: "screenshots/30-admin.png", fullPage: true });

  const visitor = await browser.newContext();
  const tab = await visitor.newPage();
  await tab.goto("/auth");
  await tab.getByRole("tab", { name: "Sign Up" }).click();
  await tab.locator("#signup-email").fill(`stranger-${Date.now()}@example.com`);
  await tab.locator("#signup-password").fill("e2e-password-123");
  let tracked = "";
  tab.on("request", (r) => {
    if (r.url().includes("/api/track")) tracked += r.postData() ?? "";
  });
  await tab.getByRole("button", { name: "Create Account" }).click();
  await expect(tab.getByText("Sign-up is closed")).toBeVisible();
  // the refusal is reported as a problem from the browser too: the failed request and the message shown
  await expect.poll(() => tracked, { timeout: 15_000 }).toContain('"api_error"');
  expect(tracked).toContain("403 POST /api/auth/signup");
  await expect.poll(() => tracked, { timeout: 15_000 }).toContain('"toast_error"');
  expect(tracked).toContain("Sign-up is closed");
  await tab.getByRole("tab", { name: "Sign In" }).click();
  await tab.locator("#signin-email").fill(email);
  await tab.locator("#signin-password").fill(password);
  await tab.getByRole("button", { name: "Sign In" }).click();
  await tab.waitForURL("**/dashboard");
  // the account starts with the sample book; its card shows the beginning of the text
  await expect(tab.getByTestId("book-card")).toHaveCount(1);
  await expect(tab.getByTestId("book-preview")).toContainText("Les Étoiles", { timeout: 30_000 });
  await tab.screenshot({ path: "screenshots/31-library-sample.png", fullPage: true });
  await visitor.close();

  // the login link signs in without the form and opens the sample book in the reader
  const guest = await browser.newContext();
  const direct = await guest.newPage();
  await direct.goto(`/auth#login=${encodeURIComponent(email)}:${encodeURIComponent(password)}`);
  await direct.waitForURL("**/read/**");
  expect(direct.url()).not.toContain(password);
  await expect(direct.getByTestId("reader-help")).toBeVisible();
  await direct.getByRole("button", { name: "Got it" }).click();
  await expect(direct.locator("[data-sentence]").first()).toContainText("Les Étoiles");
  await direct.screenshot({ path: "screenshots/32-direct-link-reader.png", fullPage: false });
  await guest.close();

  // restore the switch, remove the account
  if (wasOpen === "Close sign-up") {
    await page.getByTestId("signup-switch").click();
    await expect(page.getByTestId("signup-switch")).toHaveText("Close sign-up");
  }
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: `Delete ${email}` }).click();
  await expect(page.getByRole("cell", { name: email, exact: true })).toHaveCount(0);
});
