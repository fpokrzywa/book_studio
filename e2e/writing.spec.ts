import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

async function noSeriousA11y(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function testModel(page: Page) {
  await page.goto("/ai-settings");
  await page.getByLabel("Provider", { exact: true }).selectOption("mock");
  await page.getByRole("button", { name: "Add provider" }).click();
  await expect(page.getByRole("article", { name: /Built-in test model/ })).toBeVisible();
}

test("Phase 06 acceptance: a three-chapter book drafted by section, stopped, resumed, history inspected; locked chapter untouched", async ({
  page,
  core,
}) => {
  void core;
  await testModel(page);
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("Three Small Chapters");
  await page.getByLabel("Target length in words").fill("3000");
  await page.getByLabel("Main promise to the reader").fill("Keep a mower running");
  await page.getByLabel("How many chapters?").fill("3");
  await page.getByRole("button", { name: "Create book" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Three Small Chapters" })).toBeVisible();
  const bookUrl = page.url();

  await page.goto(`${bookUrl}/plan?tab=outline`);
  await page.getByLabel("Model").selectOption({ label: "mock-writer" });
  await page.getByRole("button", { name: "Propose an outline" }).click();
  const proposal = page.getByRole("region", { name: "AI proposal, version 1" });
  await proposal.getByRole("button", { name: "Approve this outline" }).click({ timeout: 15_000 });
  await page.getByRole("region", { name: "Approved outline, version 1" }).getByRole("button", { name: "Apply to manuscript" }).click();
  await expect(page.getByText("New empty chapters")).toBeVisible();

  // The author locks the third chapter against AI changes.
  await page.goto(bookUrl);
  await page.locator(".tree .tree-main > a", { hasText: "Tools" }).click();
  await page.getByLabel("Lock against AI changes").click();
  await expect(page.getByLabel("Lock against AI changes")).toBeChecked();
  const toolsUrl = page.url();

  // Draft the whole book, stopping after each section for review.
  await page.goto(`${bookUrl}/plan?tab=draft`);
  await page.getByLabel("Every eligible chapter").check();
  await page.getByLabel("Model").selectOption({ label: "mock-writer" });
  await page.getByLabel("Stop after each section so I can review it").check();
  await page.getByRole("button", { name: "Estimate" }).click();
  await expect(page.getByRole("row", { name: /Tools .*Locked or approved/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /Foundations .* 2 / })).toBeVisible();
  await page.getByRole("button", { name: /Start drafting 2 chapter/ }).click();
  await page.getByRole("link", { name: "Follow the drafts section by section" }).click();

  const first = page.getByRole("article", { name: "Foundations" });
  await expect(first.getByText("Waiting for your review", { exact: true })).toBeVisible({ timeout: 20_000 });
  await noSeriousA11y(page);

  // Stop (pause) and resume.
  await first.getByRole("button", { name: "Pause" }).click();
  await expect(first.getByText("Paused", { exact: true })).toBeVisible();
  await first.getByRole("button", { name: "Resume" }).click();
  await expect(first.getByText("Waiting for your review", { exact: true })).toBeVisible();

  // Review gate: edit the first section, approve; then approve the second.
  const box = first.getByLabel(/Section text \(edit before approving/);
  await box.fill("My own opening for this section.");
  await first.getByRole("button", { name: "Approve section and continue" }).click();
  // The second section is drafted with the first one as context, then waits for review too.
  await expect(box).toHaveValue(/Section 2 of/, { timeout: 20_000 });
  await first.getByRole("button", { name: "Approve section and continue" }).click();
  await expect(first.getByText("Ready for review in the chapter", { exact: true })).toBeVisible({ timeout: 20_000 });

  const second = page.getByRole("article", { name: "First Steps" });
  const box2 = second.getByLabel(/Section text \(edit before approving/);
  await expect(box2).toHaveValue(/Section 1 of/, { timeout: 20_000 });
  await second.getByRole("button", { name: "Approve section and continue" }).click();
  await expect(box2).toHaveValue(/Section 2 of/, { timeout: 20_000 });
  await second.getByRole("button", { name: "Approve section and continue" }).click();
  await expect(second.getByText("Ready for review in the chapter", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("article", { name: "Tools" })).toHaveCount(0);

  // Inspect the draft's job history.
  await first.getByText("Job history for this draft").click();
  await expect(first.getByText(/1\. .*attempt 1: succeeded · draft · mock \/ mock-writer/)).toBeVisible();
  await expect(first.getByText(/Context for section 1/).first()).toBeVisible();

  // Generated text is a suggestion only; the locked chapter has nothing waiting.
  await first.getByRole("link", { name: /Review the chapter draft/ }).click();
  await expect(page.getByText(/An AI suggestion is waiting for your review/)).toBeVisible();
  await expect(page.getByText(/^Not saved yet/)).toBeVisible();
  await page.goto(toolsUrl);
  await expect(page.getByLabel("Lock against AI changes")).toBeChecked();
  await expect(page.getByText(/An AI suggestion is waiting for your review/)).toHaveCount(0);
});

const REPEATED =
  "Drain the old oil while the engine is warm so that it flows out quickly and carries the dirt with it.";
const TEXT = [
  "In 2019, 64% of mower repairs were caused by old oil. Studies show that fresh oil doubles engine life.",
  REPEATED,
  "Change the oil every season and keep the mower dry.",
  REPEATED,
].join("\n\n");

test("quality checks find a repeated paragraph and unsupported facts; editor actions show a diff", async ({
  page,
  core,
}) => {
  void core;
  await testModel(page);
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("Oil Book");
  await page.getByRole("button", { name: "Create book" }).click();
  await page.getByLabel("New chapter title").fill("Oil");
  await page.getByRole("button", { name: "Add chapter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Oil", exact: true })).toBeVisible();
  const chapterUrl = page.url();
  await page.getByLabel("Plain text editor").check();
  await page.getByLabel("Chapter text (Markdown)").fill(TEXT);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/^Saved as revision 1/)).toBeVisible();
  const bookUrl = chapterUrl.replace(/\/chapters\/.*$/, "");

  await page.goto(`${bookUrl}/write?tab=quality`);
  await page.getByRole("button", { name: "Run checks" }).click();
  await expect(page.getByText(/They do not decide whether a statement is true/)).toBeVisible();
  const dups = page.getByRole("region", { name: "Duplicated paragraphs" });
  await expect(dups.getByText(/The same paragraph appears 2 times/)).toBeVisible();
  const claims = page.getByRole("region", { name: "Factual-looking sentences without a citation" });
  await expect(claims.getByRole("listitem")).toHaveCount(2);
  await noSeriousA11y(page);
  await claims.getByLabel("Your decision").first().selectOption("needs_source");
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Factual-looking sentences without a citation" }).getByLabel("Your decision").first(),
  ).toHaveValue("needs_source");

  // Editor action on a selection: the suggestion shows the change word by word.
  await page.goto(chapterUrl);
  await page.getByLabel("Plain text editor").check();
  const area = page.getByLabel("Chapter text (Markdown)");
  await area.evaluate((el: HTMLTextAreaElement, end: number) => {
    el.focus();
    el.setSelectionRange(0, end);
  }, TEXT.indexOf("\n\n"));
  const panel = page.getByRole("region", { name: "AI assist" });
  if (!(await panel.isVisible())) await page.getByRole("button", { name: /AI assist/ }).click();
  await panel.getByLabel("Editor action on the selection").selectOption("clarity");
  await panel.getByLabel("Model").selectOption({ label: "mock-writer" });
  await area.evaluate((el: HTMLTextAreaElement, end: number) => {
    el.focus();
    el.setSelectionRange(0, end);
  }, TEXT.indexOf("\n\n"));
  // The panel reads the editor's selection when the request form gets focus.
  await panel.getByLabel("What should it do?").click();
  await expect(panel.getByText(/Replaces the selected passage/)).toBeVisible();
  await panel.getByRole("button", { name: "Ask" }).click();
  const diff = panel.getByRole("figure", { name: /Changes, word by word/ });
  await expect(diff).toBeVisible({ timeout: 20_000 });
  await expect(diff.locator("del").first()).toBeVisible();
  await expect(diff.locator("ins").first()).toBeVisible();
  await noSeriousA11y(page);
});
