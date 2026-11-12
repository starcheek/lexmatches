import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { removeSampleBooks } from "./sample";

// Runs against whatever translator the api has (Claude when ANTHROPIC_API_KEY is set, else the mock).
// Assertions only rely on the v2 data contract, not on specific translations.
// Cost with Claude: test 1 ~1 short page, test 2 two PDF pages (page 1 + the prefetched page 2).

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = process.env.FIXTURES_DIR ?? path.resolve(here, "../../tests/fixtures");
const shots = path.resolve(here, "../screenshots");
const shot = (page: Page, name: string, fullPage = true) => page.screenshot({ path: path.join(shots, `${name}.png`), fullPage });
const norm = (s: string | null) => (s ?? "").replace(/\s+/g, " ").trim();

const PASTED = `Le premier soir je me suis donc endormi sur le sable à mille milles de toute terre habitée. J'étais bien plus isolé qu'un naufragé sur un radeau au milieu de l'océan.

Alors vous imaginez ma surprise, au lever du jour, quand une drôle de petite voix m'a réveillé. Elle disait : « S'il vous plaît… dessine-moi un mouton ! »

J'ai sauté sur mes pieds comme si j'avais été frappé par la foudre. J'ai bien frotté mes yeux. J'ai bien regardé.`;

async function signUp(page: Page, tag: string) {
  await page.goto("/auth");
  await page.getByRole("tab", { name: "Sign Up" }).click();
  await page.locator("#signup-email").fill(`e2e-${tag}-${Date.now()}@example.com`);
  await page.locator("#signup-password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create Account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Your Library" })).toBeVisible();
  await removeSampleBooks(page);
}

/** No horizontal page scroll and no text box wider than the reading column. */
async function expectNoOverflow(page: Page) {
  const r = await page.evaluate(() => {
    const article = document.querySelector("article.reading-text") as HTMLElement;
    const a = article.getBoundingClientRect();
    const wide = Array.from(article.querySelectorAll<HTMLElement>(".sentence")).filter((el) =>
      Array.from(el.getClientRects()).some((rect) => rect.right > a.right + 2 || rect.left < a.left - 2),
    ).length;
    return { scroll: document.documentElement.scrollWidth, view: window.innerWidth, wide };
  });
  expect(r.scroll).toBeLessThanOrEqual(r.view);
  expect(r.wide).toBe(0);
}

async function waitTranslated(page: Page) {
  await expect(page.getByTestId("translation-progress")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".chunk").first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("translation-progress")).toBeHidden({ timeout: 180_000 });
}

test("library → paste → translate → glosses / sentence translation / tracking → mobile → delete", async ({ page }) => {
  await signUp(page, "paste");
  await expect(page.getByText("No books yet")).toBeVisible();
  await shot(page, "01-dashboard-empty");

  // Paste a text: a text book opens straight in the reader
  await page.getByRole("button", { name: /Paste Text/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#text-title").fill("Le Petit Prince (e2e)");
  await dialog.locator("#pasted-text").fill(PASTED);
  await expect(dialog.getByLabel("Language of the text")).toHaveText("French");
  await shot(page, "02-paste-dialog", false);
  await dialog.getByRole("button", { name: "Add text" }).click();
  await expect(page).toHaveURL(/\/read\//);

  // First book ever opened in this browser: the help explains the controls, once.
  const intro = page.getByTestId("reader-help");
  await expect(intro).toBeVisible();
  await expect(intro.getByText("move line by line")).toBeVisible();
  await shot(page, "05b-reader-help", false);
  await intro.getByRole("button", { name: "Got it" }).click();
  await expect(intro).toBeHidden();
  await page.reload();
  await expect(page.locator("[data-sentence]").first()).toBeVisible();
  await expect(intro).toBeHidden(); // not again
  await page.getByRole("button", { name: "Keyboard shortcuts" }).click(); // top bar, next to the title
  await expect(intro.getByText("Translations of the current line only")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(intro).toBeHidden();

  // Untranslated: paragraphs + sentences from the source, a clear call to action, nothing docked but the player
  await expect(page.getByText("This page isn't translated yet")).toBeVisible();
  await expect(page.locator("article .para")).toHaveCount(3);
  await expect(page.locator("[data-sentence]")).toHaveCount(7);
  await expect(page.getByTestId("book-meta")).toHaveText(/French → English/);

  // Translate: progress, then glossed sentences
  await page.getByRole("button", { name: "Translate page" }).click();
  await waitTranslated(page);
  await expect(page.getByTestId("book-meta")).toContainText("1 of 1 pages translated");
  await expect(page.locator("[data-sentence]")).toHaveCount(7);
  // one comfortable size for all source text, wrapping inside the column
  const sizes = await page.locator(".chunk-src").evaluateAll((els) => [...new Set(els.map((e) => getComputedStyle(e).fontSize))]);
  expect(sizes).toHaveLength(1);
  expect(parseFloat(sizes[0])).toBeGreaterThanOrEqual(18);
  await expectNoOverflow(page);

  // Nothing is translated on screen until the reader asks. Lookups are counted as reading-session
  // clicks (Progress page): one phrase, then all glosses (G).
  const sessionSaved = page.waitForRequest((r) => r.url().endsWith("/api/reading-sessions") && r.method() === "POST");
  const glosses = page.getByRole("button", { name: "Glosses" });
  await expect(glosses).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(0);
  const phrase = page.locator("[data-sentence='0'] .chunk").nth(1);
  await phrase.click();
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(1);
  await expect(page.getByTestId("lookup-count")).toHaveText("1 lookup");
  await phrase.click();
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(0);
  await expect(page.getByTestId("lookup-count")).toHaveText("1 lookup"); // hiding is not a lookup
  await page.keyboard.press("g");
  await expect(glosses).toHaveAttribute("aria-pressed", "true");
  await shot(page, "10-paste-translated-glosses");
  await page.keyboard.press("g");
  await expect(glosses).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(0);
  const saved = await sessionSaved;
  expect(JSON.parse(saved.postData() ?? "{}").translation_toggle_clicks).toBeGreaterThanOrEqual(1);

  // Enter: the natural translation (and all glosses) of the current line's sentence; Enter closes it again
  const second = page.locator("[data-sentence='1']");
  await second.locator(".chunk").first().click(); // makes its line the current line
  await second.locator(".chunk").first().click();
  await page.keyboard.press("Enter");
  const help = page.getByTestId("sentence-help");
  await expect(help).toHaveCount(1);
  expect(norm(await help.locator(".sentence-help-text").textContent()).length).toBeGreaterThan(5);
  await expect(second.locator(".chunk-gloss").first()).toBeVisible();
  await expect(page.locator("[data-sentence='0'] .chunk-gloss:visible")).toHaveCount(0);
  await shot(page, "11-paste-sentence-revealed");
  await page.keyboard.press("Enter");
  await expect(help).toHaveCount(0);

  // Paragraph translations (T)
  await page.keyboard.press("t");
  await expect(page.locator(".para-translation")).toHaveCount(3);
  await shot(page, "12-paste-translations-on");
  await page.keyboard.press("t");
  await page.keyboard.press("g");
  await expect(page.locator(".para-translation")).toHaveCount(0);
  await expect(glosses).toHaveAttribute("aria-pressed", "true");

  // Read aloud on glossed text: the active chunk is highlighted inside the active sentence
  const bar = page.getByTestId("read-aloud-bar");
  await bar.getByRole("button", { name: "Read aloud" }).click();
  await expect(bar).toHaveAttribute("data-status", "playing", { timeout: 120_000 });
  await expect(page.locator("[data-sentence][data-active] .chunk[data-tts-active]")).toHaveCount(1, { timeout: 15_000 });
  // tapping a sentence while listening jumps playback there
  await page.locator("[data-sentence='4']").click();
  await expect(bar).toHaveAttribute("data-active", /:4$/);
  // a paragraph is one clip: the next sentence of the same paragraph is a seek, not a new clip
  const clipSrc = () => page.getByTestId("read-aloud-audio").evaluate((a: HTMLAudioElement) => a.src);
  await expect(page.locator("[data-sentence='4'] [data-tts-active]")).toHaveCount(1, { timeout: 60_000 }); // its clip plays
  const src = await clipSrc();
  await page.locator("[data-sentence='6']").click();
  await expect(bar).toHaveAttribute("data-active", /:6$/);
  expect(await clipSrc()).toBe(src);
  await page.locator("[data-sentence='4']").click();
  await expect(bar).toHaveAttribute("data-active", /:4$/);
  expect(await clipSrc()).toBe(src);
  await page.keyboard.press("Space");
  await expect(bar).toHaveAttribute("data-status", "paused");
  await page.waitForTimeout(1500); // a part still loading after the jump must not resume by itself
  await expect(bar).toHaveAttribute("data-status", "paused");

  // Phone width: no horizontal scroll; the docked player never covers the last line
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await expectNoOverflow(page);
  await shot(page, "13-paste-mobile", false);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(300);
  const lastBottom = await page.locator("[data-sentence]").last().evaluate((e) => e.getBoundingClientRect().bottom);
  const dockTop = await page.getByTestId("reader-dock").evaluate((e) => e.getBoundingClientRect().top);
  expect(lastBottom).toBeLessThan(dockTop);
  await shot(page, "14-paste-mobile-end", false);

  // Dark mode (reader menu)
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "More actions" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Dark mode" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "15-paste-dark", false);
  await page.getByRole("button", { name: "More actions" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Dark mode" }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);

  // Progress counts the help requests of this page
  await page.getByRole("button", { name: "Back to library" }).click();
  await page.getByRole("button", { name: "Progress" }).click();
  await expect(page.getByText(/1 of 1 pages tracked/)).toBeVisible();
  await shot(page, "16-progress");

  // Delete the book from the library
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Actions for Le Petit Prince (e2e)" }).click();
  await page.getByRole("menuitem", { name: "Delete book" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("book-card")).toHaveCount(0);
  await expect(page.getByText("No books yet")).toBeVisible();
});

test("upload PDF → process → listen (untranslated) → auto-advance → translate → prefetch next page", async ({ page }) => {
  const title = "Le Tour du monde (e2e)";
  await page.addInitScript(() => localStorage.setItem("lexmatches:reader-intro:v1", "1")); // help already seen
  await signUp(page, "pdf");

  // Upload; the library polls until the pages are extracted
  await page.getByRole("button", { name: /Upload a book/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#file").setInputFiles(path.join(fixtures, "fr_clean_prose.pdf"));
  await expect(dialog.locator("#file-title")).toHaveValue("fr_clean_prose"); // title suggested from the file name
  await dialog.locator("#file-title").fill(title);
  await page.waitForTimeout(400);
  await shot(page, "03-upload-dialog", false);
  await dialog.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(dialog).toBeHidden();
  const card = page.getByTestId("book-card").filter({ hasText: title });
  await expect(card).toHaveAttribute("data-status", "completed", { timeout: 60_000 });
  // pages are reading units of ~1,500–1,800 characters, not PDF pages (this 2-page PDF gives 4)
  await expect(card.getByText("4 pages")).toBeVisible();
  await shot(page, "04-dashboard-book");

  // Reader, page 1 untranslated
  await card.getByRole("button", { name: title, exact: true }).click();
  await expect(page).toHaveURL(/\/read\//);
  await expect(page.getByTestId("page-indicator")).toHaveText("Page 1 of 4");
  await expect(page.getByText("This page isn't translated yet")).toBeVisible();
  await expect(page.getByText("Phileas Fogg").first()).toBeVisible();
  await expectNoOverflow(page);
  await shot(page, "05-reader-untranslated");

  // Read aloud from the first visible sentence (server Piper TTS, exact word timings)
  const audio = page.getByTestId("read-aloud-audio");
  const audioState = () => audio.evaluate((a: HTMLAudioElement) => ({ t: a.currentTime, paused: a.paused, rate: a.playbackRate }));
  const ttsMeta = page.waitForResponse((r) => r.url().endsWith("/api/tts") && r.request().method() === "POST", { timeout: 180_000 });
  const ttsAudio = page.waitForResponse((r) => r.url().includes("/api/tts/audio/"), { timeout: 180_000 });
  const firstSentence = norm(await page.locator("[data-sentence]").first().textContent());
  const bar = page.getByTestId("read-aloud-bar");
  await bar.getByRole("button", { name: "Read aloud" }).click();
  const metaResponse = await ttsMeta;
  expect(metaResponse.status()).toBe(200);
  const meta = await metaResponse.json();
  const requested: string = JSON.parse(metaResponse.request().postData() ?? "{}").text;
  // one request = the first sentence plus the following sentences of its paragraph (or a piece of a very long one)
  expect(requested.startsWith(firstSentence) || firstSentence.startsWith(requested)).toBe(true);
  expect(meta.words).toHaveLength(requested.split(/\s+/).filter(Boolean).length);
  expect(meta.duration).toBeGreaterThan(0.5);
  const audioResponse = await ttsAudio;
  expect(audioResponse.headers()["content-type"]).toBe("audio/mpeg");
  expect(audioResponse.headers()["cache-control"]).toContain("immutable");
  await expect.poll(async () => (await audioState()).t, { timeout: 15_000 }).toBeGreaterThan(0.3);
  expect((await audioState()).paused).toBe(false);

  // the highlighted word moves with the audio, inside the highlighted sentence
  const seen = new Set<string>();
  for (let i = 0; i < 16; i++) {
    const active = page.locator("[data-sentence][data-active] [data-tts-active]");
    if (await active.count()) seen.add((await active.first().textContent()) ?? "");
    await page.waitForTimeout(150);
  }
  expect(seen.size).toBeGreaterThan(2);
  await shot(page, "06-reader-tts-playing", false);

  // Space pauses / resumes; speed changes playbackRate
  await page.keyboard.press("Space");
  await expect.poll(async () => (await audioState()).paused).toBe(true);
  await expect(bar.getByRole("button", { name: "Read aloud" })).toBeVisible();
  const pausedAt = (await audioState()).t;
  await page.waitForTimeout(600);
  expect((await audioState()).t).toBeCloseTo(pausedAt, 2);
  await page.keyboard.press("Space");
  await expect.poll(async () => (await audioState()).paused).toBe(false);
  await bar.getByTestId("read-aloud-rate").click(); // 1 -> 1.2
  await expect.poll(async () => (await audioState()).rate).toBe(1.2);

  // The MP3 decodes and its length matches the timing metadata
  const decoded = await page.evaluate(async (url) => {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${localStorage.getItem("lexmatches:token")}` } });
    return (await new AudioContext().decodeAudioData(await res.arrayBuffer())).duration;
  }, meta.audio_url);
  expect(Math.abs(decoded - meta.duration)).toBeLessThan(0.15);

  // Skip ( ] ) to the last sentence; playback continues on page 2 by itself
  const lastIndex = await page.locator("[data-sentence]").last().getAttribute("data-sentence");
  for (let i = 0; i < 80 && (await bar.getAttribute("data-active")) !== `1:${lastIndex}`; i++) {
    await page.keyboard.press("]");
    await page.waitForTimeout(200);
  }
  await expect(bar).toHaveAttribute("data-active", `1:${lastIndex}`);
  for (let i = 0; i < 20 && !(await page.getByText("Page 2 of 4").count()); i++) {
    await page.keyboard.press("]");
    await page.waitForTimeout(250);
  }
  await expect(page.getByTestId("page-indicator")).toHaveText("Page 2 of 4", { timeout: 120_000 });
  await expect(bar).toHaveAttribute("data-active", /^2:/, { timeout: 60_000 });
  await expect(bar).toHaveAttribute("data-status", "playing", { timeout: 60_000 });
  await expect.poll(async () => (await audioState()).t, { timeout: 30_000 }).toBeGreaterThan(0.3);
  await shot(page, "08-reader-tts-page2-autoadvance", false);
  await bar.getByTitle("Stop").click();
  await expect.poll(async () => (await audioState()).paused).toBe(true);

  // Back with the page button (arrow keys belong to the lines); translate page 1; sentences appear
  // progressively, then page 2 is translated ahead
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByTestId("page-indicator")).toHaveText("Page 1 of 4");
  await page.getByRole("button", { name: "Translate page" }).click();
  await expect(page.getByTestId("translation-progress")).toBeVisible();
  await shot(page, "07-reader-translating", false);
  await waitTranslated(page);
  await expectNoOverflow(page);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.keyboard.press("g"); // all glosses, for the screenshots
  await shot(page, "09-reader-translated");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoOverflow(page);
  await shot(page, "09-reader-translated-mobile", false);
  await page.setViewportSize({ width: 1440, height: 900 });
  // prefetch: the next page is being (or has been) translated without visiting it
  const bookId = page.url().split("/read/")[1];
  await expect
    .poll(
      () =>
        page.evaluate(async (id) => {
          const res = await fetch(`/api/books/${id}/pages?numbers=2`, {
            headers: { Authorization: `Bearer ${localStorage.getItem("lexmatches:token")}` },
          });
          return (await res.json())[0].status;
        }, bookId),
      { timeout: 30_000 },
    )
    .toMatch(/processing|completed/);
});

test("logged-out demo: glosses, tap for translation, browser voice (mobile layout)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const demo = page.locator("#demo");
  await demo.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("walkthrough").locator("li")).toHaveCount(4);
  // the demo starts untranslated on screen; tapping a phrase shows its gloss and counts one lookup
  await expect(demo.locator(".chunk").first()).toBeVisible();
  await expect(demo.locator(".chunk-gloss:visible")).toHaveCount(0);
  await demo.locator(".chunk").nth(2).click();
  await expect(demo.locator(".chunk-gloss:visible")).toHaveCount(1);
  await expect(demo.locator(".chunk-gloss:visible")).toHaveText("bearing");
  await expect(demo.getByTestId("lookup-count")).toHaveText("1 lookup");
  // arrows work on the demo while it is being used: next line (dot), then the whole page on / off
  await expect(demo.getByTestId("line-dot")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
  await expect(demo.locator(".chunk-gloss:visible")).toHaveCount(await demo.locator(".chunk").count());
  await expect(demo.getByTestId("lookup-count")).toHaveText("2 lookups");
  await page.keyboard.press("ArrowLeft");
  await expect(demo.locator(".chunk-gloss:visible")).toHaveCount(1); // the phrase looked up by hand stays
  const bar = page.getByTestId("read-aloud-bar");
  await bar.getByRole("button", { name: "Read aloud" }).click();
  // no server request for the demo; the player says which voice it uses
  await expect(bar.getByRole("status")).toHaveText(/Browser voice|No French voice|Speech failed|not supported/, { timeout: 10_000 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.waitForTimeout(300);
  await demo.screenshot({ path: path.join(shots, "17-demo-mobile.png") });
  await page.setViewportSize({ width: 1440, height: 900 });
  await demo.scrollIntoViewIfNeeded();
  await demo.screenshot({ path: path.join(shots, "17-demo-desktop.png") });
});
