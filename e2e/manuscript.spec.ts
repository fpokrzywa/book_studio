import { readFileSync } from "node:fs";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const FIX = path.resolve(__dirname, "..", "fixtures");

async function noSeriousA11y(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function importFixture(page: Page, title: string): Promise<string> {
  await page.goto("/import");
  await page.getByLabel("File", { exact: true }).setInputFiles(path.join(FIX, "import", "multi-chapter.html"));
  await page.getByRole("button", { name: "Show what will be imported" }).click();
  await expect(page.getByText(/3 chapters detected/)).toBeVisible();
  await expect(page.getByText(/Removed unsafe or unsupported embedded content/)).toBeVisible();
  await noSeriousA11y(page);
  await page.getByLabel("New book title").fill(title);
  await page.getByRole("button", { name: /Import 3 chapters/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  return page.url();
}

function chapterLinks(page: Page) {
  return page.locator(".tree .tree-main > a");
}

test("Phase 02 acceptance: import, edit, restart, round-trip, restore, reorder, export, backup and restore", async ({
  page,
  core,
}) => {
  const bookUrl = await importFixture(page, "The Quiet Engine");
  await expect(chapterLinks(page)).toHaveText([
    "Chapter One: Waking the Engine",
    "Chapter Two: Torque",
    "Chapter Three: Running",
  ]);
  await noSeriousA11y(page);

  // Edit Chapter Two in the source editor and check the live preview renders every structure.
  await chapterLinks(page).nth(1).click();
  await expect(page.getByRole("heading", { level: 1, name: "Chapter Two: Torque" })).toBeVisible();
  const preview = page.getByRole("document", { name: "Preview" });
  await expect(preview.locator("table caption")).toHaveText("Fastener torque values");
  await expect(preview.locator("pre code.language-python")).toContainText("def start(engine):");
  await expect(preview.locator("math")).toHaveCount(1);
  const editor = page.getByLabel("Chapter text (Markdown)");
  await editor.click();
  await page.keyboard.press("Control+End");
  await page.keyboard.type("\n\nTighten bolts in a star pattern [@smith2020, p. 4].");
  await expect(preview.locator("cite.citation")).toHaveText("(smith2020, p. 4)");
  await page.keyboard.press("Control+s");
  await expect(page.getByText(/Saved as revision 2/)).toBeVisible();
  await noSeriousA11y(page);

  // Restart Core: saved revision and an autosaved draft both survive.
  await page.keyboard.type(" Unsaved tail.");
  await expect(page.getByText(/Draft autosaved/)).toBeVisible({ timeout: 10_000 });
  await core.restart();
  await page.reload();
  await expect(page.getByText(/Recovered unsaved changes/)).toBeVisible();
  await page.getByLabel("Plain text editor").check();
  const plain = page.getByLabel("Chapter text (Markdown)");
  await expect(plain).toHaveValue(/Tighten bolts in a star pattern \[@smith2020, p\. 4\]\. Unsaved tail\.$/);
  await expect(plain).toHaveValue(/\| Bolt \| 12 Nm \|/);
  await expect(plain).toHaveValue(/: Fastener torque values/);
  await page.getByRole("button", { name: "Discard changes" }).click();
  await expect(plain).toHaveValue(/p\. 4\]\.\n?$/);

  // History: compare 1 vs 2, restore revision 1 as revision 3; revision 2 stays.
  await page.getByRole("button", { name: "History" }).click();
  const history = page.getByRole("dialog", { name: /History of/ });
  const versions = history.locator(".revision-table td > strong");
  await expect(versions).toHaveText(["Revision 2", "Revision 1"]);
  await history.getByLabel("Older").nth(1).check();
  await history.getByLabel("Newer").nth(0).check();
  await expect(history.locator("table.diff ins")).toContainText("Tighten bolts");
  await noSeriousA11y(page);
  await history.getByRole("button", { name: "Restore" }).click();
  await page.getByRole("button", { name: "Restore as new revision" }).click();
  await expect(versions).toHaveText(["Revision 3", "Revision 2", "Revision 1"]);
  await expect(history.getByText(/Restored from revision 1/).first()).toBeVisible();
  await history.getByRole("button", { name: "Close" }).click();
  await expect(plain).not.toHaveValue(/Tighten bolts/);

  // Reorder with the keyboard-equivalent buttons: Chapter Three to the top.
  await page.goto(bookUrl);
  await page.getByRole("button", { name: "Move Chapter Three: Running up" }).click();
  await expect(chapterLinks(page).nth(1)).toHaveText("Chapter Three: Running");
  await page.getByRole("button", { name: "Move Chapter Three: Running up" }).click();
  await expect(chapterLinks(page)).toHaveText([
    "Chapter Three: Running",
    "Chapter One: Waking the Engine",
    "Chapter Two: Torque",
  ]);
  // ...and with drag and drop: Chapter Two before Chapter One.
  await page.locator(".tree-row", { hasText: "Chapter Two: Torque" }).dragTo(
    page.locator(".tree-row", { hasText: "Chapter One: Waking the Engine" }),
    { targetPosition: { x: 40, y: 5 } },
  );
  await expect(chapterLinks(page)).toHaveText([
    "Chapter Three: Running",
    "Chapter Two: Torque",
    "Chapter One: Waking the Engine",
  ]);

  // Export HTML in the new order; image, caption, citation and math references still resolve.
  await page.getByRole("button", { name: "Export HTML" }).click();
  const htmlDownload = page.waitForEvent("download");
  await page.getByRole("link", { name: /Download The Quiet Engine\.html/ }).click();
  const html = readFileSync(await (await htmlDownload).path(), "utf8");
  expect(html.indexOf("Chapter Three: Running")).toBeLessThan(html.indexOf("Chapter Two: Torque"));
  expect(html.indexOf("Chapter Two: Torque")).toBeLessThan(html.indexOf("Chapter One: Waking the Engine"));
  for (const needle of ["data:image/png;base64,", "<figcaption>", "<caption>Fastener torque values</caption>",
                        'data-keys="smith2020"', "<math", 'class="footnotes"']) {
    expect(html).toContain(needle);
  }

  // Backup, then restore it as a new book from the library.
  await page.getByRole("button", { name: "Create backup" }).click();
  const backupDownload = page.waitForEvent("download");
  await page.locator(".panel", { hasText: "Backup" }).getByRole("link", { name: /\.pbsbak\.zip$/ }).click();
  const backupPath = await (await backupDownload).path();
  await page.goto("/");
  await page.getByLabel("Backup file to restore").setInputFiles(backupPath);
  await expect(page.getByRole("heading", { level: 1, name: "The Quiet Engine (restored)" })).toBeVisible();
  await expect(chapterLinks(page)).toHaveText([
    "Chapter Three: Running",
    "Chapter Two: Torque",
    "Chapter One: Waking the Engine",
  ]);
  await page.goto("/");
  await expect(page.locator(".shelf .volume")).toHaveCount(2);
});

test("hostile and unreadable files are refused with an explanation", async ({ page, core }) => {
  void core;
  for (const [file, message] of [
    ["import/scanned.pdf", /scanned/],
    ["malicious/zipbomb.docx", /zip bomb/],
    ["malicious/legacy.doc", /old Word/],
  ] as const) {
    await page.goto("/import");
    await page.getByLabel("File", { exact: true }).setInputFiles(path.join(FIX, file));
    await page.getByRole("button", { name: "Show what will be imported" }).click();
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(page.getByText("The uploaded file was kept unchanged")).toBeVisible();
  }
});
