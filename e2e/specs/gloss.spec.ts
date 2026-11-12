import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Gloss layout on real model output (fixtures/gloss_verne.json: an eval run on public-domain Verne),
// served by patching the pages response, so it costs nothing and does not depend on the translator.
// Each chunk and its gloss must be one column: the gloss starts under its chunk and stays inside it,
// and the gloss must not widen the column (holes in the source line).

const here = path.dirname(fileURLToPath(import.meta.url));
const shots = path.resolve(here, "../screenshots");
const fixture = JSON.parse(fs.readFileSync(path.resolve(here, "../fixtures/gloss_verne.json"), "utf8"));

async function measure(page: Page) {
  return page.evaluate(() => {
    const chunks = Array.from(document.querySelectorAll<HTMLElement>(".chunk[data-glossed]"));
    let outside = 0;
    const widened: string[] = [];
    const tall: string[] = [];
    for (const chunk of chunks) {
      const src = chunk.querySelector<HTMLElement>(".chunk-src")!;
      const gloss = chunk.querySelector<HTMLElement>(".chunk-gloss")!;
      const range = document.createRange();
      range.selectNodeContents(src);
      const text = range.getBoundingClientRect(); // the words themselves, not the stretched box
      const range2 = document.createRange();
      range2.selectNodeContents(gloss);
      const g = range2.getBoundingClientRect();
      const box = chunk.getBoundingClientRect();
      const centred = Math.abs((g.left + g.right) / 2 - (text.left + text.right) / 2) <= 1.5;
      if (!centred || g.left < box.left - 1 || g.right > box.right + 1) outside++;
      if (g.height > 2.6 * parseFloat(getComputedStyle(gloss).fontSize) * 1.25) tall.push(`${src.textContent} / ${gloss.textContent}`);
      const em = parseFloat(getComputedStyle(src).fontSize);
      if (chunk.getBoundingClientRect().width > text.width + 1.2 * em) widened.push(`${src.textContent} / ${gloss.textContent}`); // a visible hole
    }
    return { chunks: chunks.length, outside, widened, tall, scroll: document.documentElement.scrollWidth, view: window.innerWidth };
  });
}

test("glosses sit under exactly their chunk, without holes in the source line", async ({ page }) => {
  await page.route(/\/api\/books\/[^/]+\/pages(\?.*)?$/, async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const pages = await response.json();
    for (const p of pages) Object.assign(p, { translated_data: fixture.translated_data, status: "completed" });
    await route.fulfill({ response, json: pages });
  });

  await page.addInitScript(() => localStorage.setItem("lexmatches:reader-intro:v1", "1")); // help already seen
  await page.goto("/auth");
  await page.getByRole("tab", { name: "Sign Up" }).click();
  await page.locator("#signup-email").fill(`e2e-gloss-${Date.now()}@example.com`);
  await page.locator("#signup-password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create Account" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("button", { name: /Paste Text/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("#text-title").fill("Le Tour du monde (gloss e2e)");
  await dialog.locator("#pasted-text").fill(fixture.text.slice(0, 1500));
  await dialog.getByRole("button", { name: "Add text" }).click();
  await expect(page).toHaveURL(/\/read\//);
  // Glosses are hidden until the reader asks; G shows all of them.
  await expect(page.locator(".chunk").first()).toBeVisible();
  await expect(page.locator(".chunk-gloss:visible")).toHaveCount(0);
  await page.keyboard.press("g");
  await expect(page.locator(".chunk-gloss").first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await expect(page.getByText("Account created!")).toBeHidden({ timeout: 15_000 });

  for (const [name, width] of [["desktop", 1440], ["mobile", 390]] as const) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => window.scrollTo(0, 0));
    const m = await measure(page);
    console.log(name, JSON.stringify(m));
    expect(m.chunks).toBeGreaterThan(100);
    expect(m.outside).toBe(0);
    expect(m.widened.length / m.chunks).toBeLessThan(0.03); // only a gloss word longer than its whole chunk
    expect(m.tall).toEqual([]); // no gloss taller than two lines
    expect(m.scroll).toBeLessThanOrEqual(m.view);
    await page.screenshot({ path: path.join(shots, `20-gloss-${name}.png`), fullPage: false });
    await page.screenshot({ path: path.join(shots, `20-gloss-${name}-full.png`), fullPage: true });
  }

  // Toggling glosses must not move the text: same words on the same lines at the same x, and the
  // sentence at the top of the window stays where it is. Checked mid-page, by button and by key.
  const layout = () =>
    page.evaluate(() => {
      const srcs = Array.from(document.querySelectorAll<HTMLElement>(".chunk-src"));
      const tops = [...new Set(srcs.map((e) => Math.round(e.getBoundingClientRect().top)))].sort((a, b) => a - b);
      const first = srcs.findIndex((e) => e.getBoundingClientRect().bottom > 72);
      return {
        cells: srcs.map((e) => `${tops.indexOf(Math.round(e.getBoundingClientRect().top))}:${Math.round(e.getBoundingClientRect().left)}`),
        scrollY: window.scrollY,
        tops: srcs.map((e) => Math.round(e.getBoundingClientRect().top)),
        glosses: document.querySelectorAll(".chunk[data-glossed]").length,
        // rows (index into the distinct line tops) that have a visible gloss / are the current line
        glossRows: [...new Set(srcs.filter((e) => e.parentElement!.hasAttribute("data-glossed")).map((e) => tops.indexOf(Math.round(e.getBoundingClientRect().top))))],
        // the row the current-line dot sits on (its centre is inside that row's source words)
        lineRows: (() => {
          const dot = document.querySelector<HTMLElement>('[data-testid="line-dot"]');
          if (!dot) return [];
          const d = dot.getBoundingClientRect();
          const y = d.top + d.height / 2;
          const hit = srcs.find((e) => e.getBoundingClientRect().top <= y && y <= e.getBoundingClientRect().bottom);
          return hit ? [tops.indexOf(Math.round(hit.getBoundingClientRect().top))] : [-1];
        })(),
        dotLeft: document.querySelector<HTMLElement>('[data-testid="line-dot"]')?.getBoundingClientRect().left ?? null,
        textLeft: Math.min(...srcs.map((e) => e.getBoundingClientRect().left)),
        lookups: document.querySelector('[data-testid="lookup-count"]')?.textContent ?? "",
      };
    });
  const lookups = async () => parseInt((await layout()).lookups, 10);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 600 }); // short window: room to scroll in both modes
    await page.evaluate(() => window.scrollTo(0, 500));
    await page.waitForTimeout(400);
    const on = await layout();
    expect(on.glosses).toBeGreaterThan(0);
    await page.getByRole("button", { name: "Glosses" }).click(); // mouse; focus must not swallow later keys
    const off = await layout();
    expect(off.glosses).toBe(0);
    expect(off.cells).toEqual(on.cells);
    expect(off.tops).toEqual(on.tops); // no word moved, horizontally or vertically
    expect(off.scrollY).toBe(on.scrollY);
    await page.screenshot({ path: path.join(shots, `21-gloss-off-${width}.png`), fullPage: false });
    await page.keyboard.press("g");
    const again = await layout();
    expect(again.glosses).toBe(on.glosses);
    expect(again.cells).toEqual(on.cells);
    expect(again.tops).toEqual(on.tops);

    // Lookups, with all glosses off: click one phrase -> only its gloss; arrows work line by line.
    await page.keyboard.press("g");
    const before = await lookups();
    const phrase = page.locator(".chunk").nth(on.tops.findIndex((t) => t > 150)); // a phrase in view
    await phrase.click();
    let now = await layout();
    expect(now.glosses).toBe(1);
    expect(now.tops).toEqual(on.tops);
    expect(await lookups()).toBe(before + 1);
    await page.waitForTimeout(400); // the dot slides for 0.3 s
    now = await layout();
    expect(now.lineRows).toHaveLength(1); // the clicked phrase's line is the current line
    const row = now.lineRows[0];
    expect(row).toBeGreaterThanOrEqual(0);
    expect(now.dotLeft!).toBeLessThan(now.textLeft); // in the left margin, on screen
    expect(now.dotLeft!).toBeGreaterThanOrEqual(0);
    await page.screenshot({ path: path.join(shots, `23-lookup-dot-${width}.png`), fullPage: false });
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(100);
    const mid = await layout(); // mid-animation: between the two lines
    await page.waitForTimeout(350);
    now = await layout();
    expect(now.lineRows).toEqual([row + 1]);
    if (width === 1440) expect(mid.lineRows).not.toEqual([row + 1]);
    await page.keyboard.press("ArrowRight"); // the whole page on
    now = await layout();
    expect(now.glosses).toBe(on.glosses);
    expect(now.cells).toEqual(on.cells);
    expect(await lookups()).toBe(before + 2);
    await page.keyboard.press("ArrowLeft"); // same key meaning: the whole page off, not counted
    now = await layout();
    expect(now.glossRows).toEqual([row]); // the phrase looked up by hand stays
    expect(await lookups()).toBe(before + 2);
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("ArrowUp");
    await page.waitForTimeout(400);
    expect((await layout()).lineRows).toEqual([row - 1]);
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("ArrowDown"); // walks down; the page scrolls smoothly with the line
      await page.waitForTimeout(120);
    }
    await page.waitForTimeout(900);
    now = await layout();
    expect(now.lineRows).toEqual([row + 11]);
    expect(now.scrollY).toBeGreaterThan(on.scrollY);
    const lineTop = now.tops[now.cells.findIndex((c) => c.startsWith(`${row + 11}:`))];
    expect(lineTop).toBeGreaterThan(72);
    expect(lineTop).toBeLessThan(600 - 88);
    await phrase.click(); // hide it again
    await page.keyboard.press("g"); // all glosses back on for the next width
  }

  // Line mode (L / "Line"): only the current line shows its glosses, they follow ↑ / ↓, nothing moves.
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload(); // a fresh visit: no current line yet, so "Line" starts at the top of the window
  await expect(page.locator(".chunk").first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  await page.keyboard.press("g"); // all glosses off
  const absolute = (l: { tops: number[]; scrollY: number }) => l.tops.map((t) => t + l.scrollY); // independent of scrolling
  const plain = await layout();
  expect(plain.glosses).toBe(0);
  const lookupsBefore = await lookups();
  await page.getByRole("button", { name: "Line" }).click();
  await page.waitForTimeout(400);
  let lined = await layout();
  expect(lined.lineRows).toHaveLength(1);
  const lineRow = lined.lineRows[0];
  expect(lined.glossRows).toEqual([lineRow]); // glosses on the current line and nowhere else
  expect(lined.glosses).toBe(lined.cells.filter((c) => c.startsWith(`${lineRow}:`)).length); // every phrase of it
  expect(absolute(lined)).toEqual(absolute(plain));
  expect(await lookups()).toBe(lookupsBefore + 1);
  await page.screenshot({ path: path.join(shots, "24-line-mode.png"), fullPage: false });
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(400);
  lined = await layout();
  expect(lined.lineRows).toEqual([lineRow + 2]);
  expect(lined.glossRows).toEqual([lineRow + 2]); // the glosses moved with the line
  expect(absolute(lined)).toEqual(absolute(plain));
  expect(await lookups()).toBe(lookupsBefore + 1); // following the text is not counted again
  await page.keyboard.press("l");
  expect((await layout()).glosses).toBe(0);
  await page.keyboard.press("g"); // all glosses back on for the text-size check

  // Text size: A- / A+ and the - / + keys scale the text and the column with it.
  await page.setViewportSize({ width: 1440, height: 900 });
  const metrics = () =>
    page.evaluate(() => {
      const a = document.querySelector<HTMLElement>("article.reading-text")!;
      return { font: parseFloat(getComputedStyle(a).fontSize), width: a.getBoundingClientRect().width };
    });
  const base = await metrics();
  await page.keyboard.press("+");
  await page.getByRole("button", { name: "Larger text" }).click();
  const big = await metrics();
  expect(big.font).toBeGreaterThan(base.font * 1.25);
  expect(big.width).toBeGreaterThan(base.width * 1.2);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(1440);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(shots, "22-text-larger.png"), fullPage: false });
  await page.keyboard.press("-");
  await page.keyboard.press("-");
  expect((await metrics()).font).toBeCloseTo(base.font, 1);

  // clean up the book
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Actions for Le Tour du monde (gloss e2e)" }).click();
  await page.getByRole("menuitem", { name: "Delete book" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByTestId("book-card")).toHaveCount(0);
});
