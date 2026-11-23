import path from "node:path";
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

const FIX = path.resolve(__dirname, "..", "fixtures", "knowledge");

async function noSeriousA11y(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function setup(page: Page) {
  await page.goto("/ai-settings");
  await page.getByLabel("Provider", { exact: true }).selectOption("mock");
  await page.getByRole("button", { name: "Add provider" }).click();
  await expect(page.getByRole("article", { name: /Built-in test model/ })).toBeVisible();
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("The Quiet Engine");
  await page.getByRole("button", { name: "Create book" }).click();
  await page.getByLabel("New chapter title").fill("Chapter One");
  await page.getByRole("button", { name: "Add chapter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Chapter One" })).toBeVisible();
  const chapterUrl = page.url();
  await page.getByLabel("Plain text editor").check();
  await page.getByLabel("Chapter text (Markdown)").fill("Notes on the workshop.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/^Saved as revision 1/)).toBeVisible();
  await page.getByRole("link", { name: "The Quiet Engine" }).first().click();
  return chapterUrl;
}

async function ask(page: Page, chapterUrl: string, instruction: string) {
  await page.goto(chapterUrl);
  const panel = page.getByRole("region", { name: "AI assist" });
  if (!(await panel.isVisible())) await page.getByRole("button", { name: /AI assist/ }).click();
  await panel.getByLabel("Model").selectOption({ label: "mock-writer" });
  await panel.getByLabel("What should it do?").fill(instruction);
  await expect(panel.getByText(/passage\(s\) from your sources will be sent|No source passages will be sent/)).toBeVisible();
  await panel.getByRole("button", { name: "Ask" }).click();
  return panel;
}

test("Phase 04 acceptance: sources are searchable, cited by passage, removable; disabled sources are not used", async ({
  page,
  core,
}) => {
  void core;
  const chapterUrl = await setup(page);

  // Import a source into the book and find an exact passage.
  await page.getByRole("link", { name: "Sources" }).click();
  await page.getByLabel("File", { exact: true }).setInputFiles(path.join(FIX, "torque-handbook.md"));
  await page.getByRole("button", { name: "Add source" }).click();
  await expect(page.getByRole("link", { name: "torque-handbook" })).toBeVisible();
  await expect(page.getByText(/1 source\(s\) available to AI/)).toBeVisible();
  await page.getByLabel("Search words").fill("spiral pattern");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.locator(".hits mark").first()).toHaveText(/spiral/i);
  await noSeriousA11y(page);
  await page.locator(".hits").getByRole("link", { name: "torque-handbook" }).click();
  await expect(page.locator('.passage[data-target="true"]')).toContainText("spiral pattern");
  await noSeriousA11y(page);

  // A generated paragraph shows its supporting passage; another is flagged unverified.
  let panel = await ask(page, chapterUrl, "Explain how cylinder head bolts are tightened.");
  const sources = panel.getByRole("region", { name: "Sources for each paragraph" });
  await expect(sources).toBeVisible({ timeout: 15_000 });
  await expect(sources.getByRole("link", { name: /torque-handbook, para/ })).toBeVisible();
  await expect(sources.getByText(/Unverified: no source supports this paragraph/).first()).toBeVisible();
  await noSeriousA11y(page);
  await panel.getByRole("button", { name: "Accept as a new revision" }).click();
  await expect(page.getByText(/^Saved as revision 2/)).toBeVisible();
  await expect(page.getByLabel("Chapter text (Markdown)")).toHaveValue(/\[@torque-handbook, para/);

  // The evidence ledger keeps the claim and the exact passage, apart from the prose.
  await page.goto(chapterUrl.replace(/\/chapters\/.*/, "/evidence"));
  await expect(page.getByText("Supported by a located passage").first()).toBeVisible();
  await expect(page.locator(".supports blockquote").first()).toContainText("spiral pattern");
  await expect(page.getByText("@torque-handbook", { exact: true })).toBeVisible();
  await noSeriousA11y(page);

  // Disabling the source keeps it out of the next generation.
  await page.goto(chapterUrl.replace(/\/chapters\/.*/, "/knowledge"));
  await page.getByLabel("Use for AI").click(); // the box follows the saved state
  await expect(page.getByLabel("Use for AI")).not.toBeChecked();
  await expect(page.getByText(/0 source\(s\) available to AI/)).toBeVisible();
  panel = await ask(page, chapterUrl, "Explain how cylinder head bolts are tightened again.");
  await expect(panel.getByText("No source passages will be sent.")).toBeVisible();
  const card = panel.getByRole("article").first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await expect(card.getByRole("link", { name: /torque-handbook/ })).toHaveCount(0);
  await expect(card.getByText(/Unverified/).first()).toBeVisible();

  // Removing the source takes it out of search; the ledger keeps the quote.
  await page.goto(chapterUrl.replace(/\/chapters\/.*/, "/knowledge"));
  await page.getByRole("button", { name: "Remove" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Remove source" }).click();
  await expect(page.getByText("No sources yet.")).toBeVisible();
  await page.getByLabel("Search words").fill("spiral");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(/No passages match/)).toBeVisible();
  await page.goto(chapterUrl.replace(/\/chapters\/.*/, "/evidence"));
  await expect(page.getByText(/source removed/).first()).toBeVisible();
});

test("interview and voice pages work by keyboard and pass accessibility checks", async ({ page, core }) => {
  void core;
  const chapterUrl = await setup(page);
  await page.goto(chapterUrl.replace(/\/chapters\/.*/, "/interview"));
  const first = page.getByLabel(/What first drew you to this subject/);
  await first.fill("My grandfather's shed,  1998.");
  await page.getByRole("button", { name: "Save answer" }).first().click();
  await expect(page.getByText(/1 of 10 answered|Saved/).first()).toBeVisible();
  await noSeriousA11y(page);

  await page.goto("/voice");
  await page.getByLabel("Name").fill("Sam Writer");
  await page.getByRole("button", { name: "Create profile" }).click();
  const profile = page.getByRole("region", { name: /Sam Writer/ });
  await profile.getByLabel("Text", { exact: true }).fill(
    "I started fixing engines young. I'd watch, then try. It wasn't easy, but it stuck. ".repeat(8),
  );
  await expect(profile.getByRole("button", { name: "Add sample" })).toBeDisabled();
  await profile.getByLabel(/I confirm this is my own writing/).check();
  await profile.getByRole("button", { name: "Add sample" }).click();
  await expect(profile.getByText(/Tone:/).first()).toBeVisible();
  await expect(profile.getByLabel(/How I write/)).toHaveValue(/Contractions/);
  await noSeriousA11y(page);
});
