import { readFileSync } from "node:fs";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

// Text that must survive byte-for-byte: a table, code with a tab and trailing spaces, math, a citation.
const CHAPTER_TEXT = [
  "The engine woke before dawn.",
  "",
  "| Part | Torque |",
  "|------|-------:|",
  "| Bolt | 12 Nm  |",
  "",
  "```python",
  "def start():\treturn True  ",
  "```",
  "",
  "$$E = mc^2$$ and a claim [@ref2024, p. 3].",
].join("\n");

async function createBook(page: Page, title: string, type = "technical") {
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill(title);
  await page.getByLabel("Kind of book").selectOption(type);
  await page.getByRole("button", { name: "Create book" }).click();
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
}

async function addChapter(page: Page, title: string) {
  await page.getByLabel("New chapter title").fill(title);
  await page.getByRole("button", { name: "Add chapter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
}

async function expectNoA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test("vertical slice: create book, write chapter, save, restart Core, content persists, export Markdown", async ({
  page,
  core,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "No books yet" })).toBeVisible();
  await expect(page.getByText("Local-only")).toBeVisible();
  await expectNoA11yViolations(page);

  await createBook(page, "The Quiet Engine");
  await expectNoA11yViolations(page);
  await addChapter(page, "Chapter One");

  const editor = page.getByLabel("Chapter text (Markdown)");
  await editor.fill(CHAPTER_TEXT);
  await expect(page.getByText("Unsaved changes")).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/Saved as revision 1/)).toBeVisible();
  await expectNoA11yViolations(page);

  // Crash Core hard, start it again on the same workspace, reload the page.
  await core.restart();
  await page.reload();
  await expect(page.getByLabel("Chapter text (Markdown)")).toHaveValue(CHAPTER_TEXT);
  await expect(page.getByText(/Saved as revision 1/)).toBeVisible();

  // Library still lists the book after the restart.
  await page.getByRole("link", { name: "The Quiet Engine" }).first().click();
  await expect(page.getByRole("link", { name: "Chapter One" })).toBeVisible();

  await page.getByRole("button", { name: "Export Markdown" }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: /Download The Quiet Engine\.md/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("The Quiet Engine.md");
  const file = readFileSync(await download.path(), "utf8");
  expect(file).toContain('title: "The Quiet Engine"');
  expect(file).toContain("# Chapter One {#ch-chapter-one}\n\n" + CHAPTER_TEXT + "\n");
});

test("keyboard only: create a book and save a chapter without the mouse", async ({ page, core }) => {
  void core;
  await page.goto("/");
  await page.keyboard.press("Tab"); // skip link
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.getByRole("link", { name: "New book" }).first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Start a new book" })).toBeVisible();
  await page.getByLabel("Title", { exact: true }).focus();
  await page.keyboard.type("Keyboard Book");
  await page.keyboard.press("Enter"); // submits the form
  await expect(page.getByRole("heading", { level: 1, name: "Keyboard Book" })).toBeVisible();
  await page.getByLabel("New chapter title").focus();
  await page.keyboard.type("Opening");
  await page.keyboard.press("Enter");
  const editor = page.getByLabel("Chapter text (Markdown)");
  await editor.focus();
  await page.keyboard.type("Typed with keys only.");
  await page.keyboard.press("Control+s");
  await expect(page.getByText(/Saved as revision 1/)).toBeVisible();
});

test("project isolation: each book shows only its own chapters; foreign IDs are not found", async ({
  page,
  core,
}) => {
  void core;
  await createBook(page, "Book A", "fiction");
  const bookAUrl = page.url();
  await addChapter(page, "A only");
  await page.getByLabel("Chapter text (Markdown)").fill("Secret of A.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/Saved as revision 1/)).toBeVisible();

  await createBook(page, "Book B", "memoir");
  await addChapter(page, "B only");
  const bChapterUrl = new URL(page.url());
  const bChapterId = bChapterUrl.pathname.split("/").pop();

  await page.goto(bookAUrl);
  await expect(page.getByRole("link", { name: "A only" })).toBeVisible();
  await expect(page.getByRole("link", { name: "B only" })).toHaveCount(0);

  // B's chapter addressed through A's URL must not open.
  await page.goto(`${new URL(bookAUrl).pathname}/chapters/${bChapterId}`);
  await expect(page.getByRole("heading", { name: "Chapter not found" })).toBeVisible();
});

test("archive makes a book read-only and unarchive restores it", async ({ page, core }) => {
  void core;
  await createBook(page, "Archive Me");
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.getByRole("button", { name: "Archive book" }).click();
  await expect(page.getByText("This book is archived.")).toBeVisible();
  await expect(page.getByLabel("New chapter title")).toHaveCount(0);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "No books yet" })).toBeVisible();
  await page.getByText("Archived", { exact: true }).click();
  await page.locator(".shelf").getByRole("link", { name: "Archive Me" }).click();
  await page.getByRole("button", { name: "Unarchive" }).click();
  await expect(page.getByLabel("New chapter title")).toBeVisible();
});

test("later-phase sections are visibly not implemented", async ({ page, core }) => {
  void core;
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByText("Not yet implemented (Phase 03)")).toBeVisible();
  await expect(nav.getByRole("link", { name: /Research|Knowledge|Publishing|AI settings/ })).toHaveCount(0);
  await page.goto("/publishing");
  await expect(page.getByText("Not yet implemented.")).toBeVisible();
});
