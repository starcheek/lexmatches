import { expect, type Page } from "@playwright/test";

/** A new account starts with the sample book (backend/seed): check that it arrived and was split into
 * pages, then remove it so the test goes on with an empty library. Call on the dashboard after sign-up. */
export async function removeSampleBooks(page: Page) {
  await expect(page.getByTestId("book-card")).toHaveCount(1);
  const pages = await page.evaluate(async () => {
    const headers = { Authorization: `Bearer ${localStorage.getItem("lexmatches:token")}` };
    let books: { id: string; status: string; total_pages: number }[] = [];
    for (let i = 0; i < 100; i++) {
      books = await (await fetch("/api/books", { headers })).json();
      if (books.every((b) => b.status === "completed" || b.status === "failed")) break;
      await new Promise((r) => setTimeout(r, 200));
    }
    for (const b of books) await fetch(`/api/books/${b.id}`, { method: "DELETE", headers });
    return books.map((b) => (b.status === "completed" ? b.total_pages : 0));
  });
  expect(pages.length).toBe(1);
  expect(pages[0]).toBeGreaterThan(100);
  await page.reload();
  await expect(page.getByTestId("book-card")).toHaveCount(0);
}
