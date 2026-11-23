import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

async function noSeriousA11y(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test("Phase 05 acceptance: idea → brief → AI outline (test model) → approve → skeleton; changes keep prose", async ({
  page,
  core,
}) => {
  void core;
  // The deterministic test model: no paid API, nothing leaves this computer.
  await page.goto("/ai-settings");
  await page.getByLabel("Provider", { exact: true }).selectOption("mock");
  await page.getByRole("button", { name: "Add provider" }).click();
  await expect(page.getByRole("article", { name: /Built-in test model/ })).toBeVisible();

  // The New Book wizard.
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("The Quiet Engine");
  await page.getByLabel("Kind of book").selectOption("nonfiction");
  await page.getByLabel("Target length in words").fill("12000");
  await page.getByLabel("Main promise to the reader").fill("Keep a small engine running for years");
  await page.getByLabel("How many chapters?").fill("3");
  await noSeriousA11y(page);
  await page.getByRole("button", { name: "Create book" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "The Quiet Engine" })).toBeVisible();
  const bookUrl = page.url();

  // The brief carries what the wizard captured.
  await page.getByRole("link", { name: "Plan", exact: true }).click();
  await expect(page.getByLabel("Core promise")).toHaveValue("Keep a small engine running for years");
  await noSeriousA11y(page);
  await page.getByRole("button", { name: "Approve brief" }).click();
  await expect(page.getByText(/Approved, version 1/)).toBeVisible();

  // Research fail-safe: no provider is on, so the search says so and adds nothing.
  await page.getByRole("link", { name: "Research" }).click();
  const catalogue = page.getByRole("region", { name: "Search public catalogues" });
  await catalogue.getByLabel("Search words").fill("small engine repair");
  await catalogue.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByText(/is not turned on\..*Nothing was searched/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Measured evidence" }).getByText("None yet.")).toBeVisible();
  await noSeriousA11y(page);

  // AI outline proposal from the test model.
  await page.getByRole("link", { name: "Outline" }).click();
  await page.getByLabel("Model").selectOption({ label: "mock-writer" });
  await page.getByRole("button", { name: "Propose an outline" }).click();
  const proposal = page.getByRole("region", { name: "AI proposal, version 1" });
  await expect(proposal).toBeVisible({ timeout: 15_000 });
  await expect(proposal.getByText(/3 chapters, 12,000 target words/)).toBeVisible();
  await noSeriousA11y(page);
  await proposal.getByRole("button", { name: "Approve this outline" }).click();
  const approved = page.getByRole("region", { name: "Approved outline, version 1" });
  await approved.getByRole("button", { name: "Apply to manuscript" }).click();
  await expect(approved.getByText("New empty chapters")).toBeVisible();

  // The skeleton is real: three planned chapters. Write prose into the first one.
  await page.goto(bookUrl);
  const links = page.locator(".tree .tree-main > a");
  await expect(links).toHaveText(["Foundations", "First Steps", "Tools"]);
  await links.first().click();
  await page.getByLabel("Plain text editor").check();
  await page.getByLabel("Chapter text (Markdown)").fill("My own first paragraph.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/^Saved as revision 1/)).toBeVisible();
  const chapterUrl = page.url();

  // Change the outline: rename the first chapter, remove the (empty) third, approve and apply again.
  await page.goto(`${bookUrl}/plan?tab=outline`);
  await page.getByRole("region", { name: "Approved outline, version 1" }).getByRole("button", { name: "Edit as a new draft" }).click();
  const draft = page.getByRole("region", { name: "Your outline draft" });
  await draft.getByLabel("Title of chapter 1").fill("Getting Started");
  await draft.getByRole("group", { name: "Arrange Chapter Tools" }).getByRole("button", { name: "Remove" }).click();
  await noSeriousA11y(page);
  await draft.getByRole("button", { name: "Save and approve" }).click();
  const v2 = page.getByRole("region", { name: "Approved outline, version 2" });
  await v2.getByRole("button", { name: "Apply to manuscript" }).click();
  await expect(v2.getByText("Renamed or moved")).toBeVisible();
  await expect(v2.getByText("Archived (they were empty)")).toBeVisible();

  // Prose and history survived the change.
  await page.goto(chapterUrl);
  await expect(page.getByRole("heading", { level: 1, name: "Getting Started" })).toBeVisible();
  await expect(page.getByLabel("Chapter text (Markdown)")).toHaveValue("My own first paragraph.");
  await page.getByRole("button", { name: "History" }).click();
  await expect(page.getByRole("dialog").getByText(/Revision 1/).first()).toBeVisible();
});

test("drafting the whole book from the approved outline produces suggestions only", async ({ page, core }) => {
  void core;
  await page.goto("/ai-settings");
  await page.getByLabel("Provider", { exact: true }).selectOption("mock");
  await page.getByRole("button", { name: "Add provider" }).click();
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("Draft Me");
  await page.getByLabel("Main promise to the reader").fill("Learn the basics");
  await page.getByLabel("How many chapters?").fill("2");
  await page.getByRole("button", { name: "Create book" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Draft Me" })).toBeVisible();
  const bookUrl = page.url();
  await page.goto(`${bookUrl}/plan?tab=outline`);
  await page.getByLabel("Model").selectOption({ label: "mock-writer" });
  await page.getByRole("button", { name: "Propose an outline" }).click();
  const proposal = page.getByRole("region", { name: "AI proposal, version 1" });
  await proposal.getByRole("button", { name: "Approve this outline" }).click({ timeout: 15_000 });
  await page.getByRole("region", { name: "Approved outline, version 1" }).getByRole("button", { name: "Apply to manuscript" }).click();
  await expect(page.getByText("New empty chapters")).toBeVisible();

  await page.getByRole("link", { name: "Draft chapters" }).click();
  await page.getByLabel("Every eligible chapter").check();
  await page.getByLabel("Model").selectOption({ label: "mock-writer" });
  await page.getByRole("button", { name: "Estimate" }).click();
  await expect(page.getByText(/Estimate:.*2 chapter\(s\)/)).toBeVisible();
  await expect(page.getByText(/Local model: no API charge/).first()).toBeVisible();
  await noSeriousA11y(page);
  await page.getByRole("button", { name: /Start drafting 2 chapter/ }).click();
  await expect(page.getByText(/Whole book.*done/)).toBeVisible({ timeout: 20_000 });

  // Each chapter now has a suggestion waiting; nothing was written into the manuscript.
  await page.goto(bookUrl);
  await page.locator(".tree .tree-main > a").first().click();
  await expect(page.getByText(/An AI suggestion is waiting for your review/)).toBeVisible();
  await expect(page.getByText(/^Not saved yet/)).toBeVisible();
});
