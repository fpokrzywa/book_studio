import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

async function noSeriousA11y(page: Page) {
  // The sandboxed book preview cannot run axe's script; the book's own HTML is checked by Core tests.
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .exclude("iframe.book-preview")
    .options({ iframes: false })
    .analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(
    serious.map(
      (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
    ),
  ).toEqual([]);
}

const CHAPTERS: [string, string][] = [
  [
    "Fuel and Air",
    "Small engines need clean fuel. See the [fuel guide](https://example.org/fuel). $a^2 + b^2 = c^2$.\n\n| Part | Ratio |\n|------|------:|\n| Petrol | 50 |\n| Oil | 1 |\n\n: Mixing ratios {#tbl-mix}\n",
  ],
  [
    "Ignition",
    'The spark plug fires once per turn.\n\n```python {caption="Checking the gap"}\ndef gap_ok(mm):\n    return 0.6 <= mm <= 0.8\n```\n\n$$\n\\frac{V_1}{V_2} = \\frac{N_1}{N_2}\n$$\n',
  ],
  [
    "Maintenance",
    "Clean the carburettor every season.\n\n| Task | Interval |\n|------|----------|\n| Oil | 25 hours |\n",
  ],
];

test("Phase 07 acceptance: build all formats, preview, covers from the page count, and open the package report", async ({
  page,
  core,
}) => {
  void core;
  test.setTimeout(240_000);
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("Engine Manual");
  await page.getByRole("button", { name: "Create book" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Engine Manual" }),
  ).toBeVisible();
  const bookUrl = page.url();
  for (const [title, text] of CHAPTERS) {
    await page.goto(bookUrl);
    await page.getByLabel("New chapter title").fill(title);
    await page.getByRole("button", { name: "Add chapter" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: title, exact: true }),
    ).toBeVisible();
    await page.getByLabel("Plain text editor").check();
    await page.getByLabel("Chapter text (Markdown)").fill(text);
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(page.getByText(/^Saved as revision 1/)).toBeVisible();
  }

  // Setup: template, trim and paper, matter; the rule-set version is shown.
  await page.goto(bookUrl);
  await page.getByRole("link", { name: "Publish", exact: true }).click();
  await expect(
    page.getByText("kdp-paperback-2026-11-22").first(),
  ).toBeVisible();
  await page.getByLabel("Trim size (inches)").selectOption("6x9");
  await expect(
    page.getByText(
      /KDP prints this trim with this ink and paper for 24–828 pages/,
    ),
  ).toBeVisible();
  await page.getByLabel("Copyright holder").fill("Ada Example");
  await page.getByLabel("Year").fill("2026");
  await noSeriousA11y(page);
  await page.getByRole("button", { name: "Save" }).click();

  // Build all five formats; previews say what they are.
  await page.getByRole("link", { name: "Build and preview" }).click();
  await page.getByRole("button", { name: "Build", exact: true }).click();
  const table = page.getByRole("table", { name: "Built files" });
  for (const name of [
    "EPUB",
    "Print interior PDF",
    "Word (DOCX)",
    "HTML",
    "Markdown (with images)",
  ]) {
    await expect(table.getByRole("link", { name, exact: true })).toBeVisible({
      timeout: 60_000,
    });
  }
  await page.getByRole("button", { name: "Show reading preview" }).click();
  await expect(
    page.getByText("Byte-identical to your last HTML export."),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Page 1 of the print layout" }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/they are not the PDF file/)).toBeVisible();
  await noSeriousA11y(page);

  // Cover: sized from the final page count of the PDF just built.
  await page.getByRole("link", { name: "Cover" }).click();
  const size = page.getByRole("region", {
    name: "Size from the final page count",
  });
  await expect(size.getByText(/Sized from the final page count/)).toBeVisible();
  await page
    .getByRole("button", { name: "Build covers from the latest print PDF" })
    .click();
  await expect(page.getByRole("link", { name: "Print cover PDF" })).toBeVisible(
    { timeout: 30_000 },
  );
  await expect(
    page.getByRole("img", { name: "The eBook front cover as built" }),
  ).toBeVisible();
  await noSeriousA11y(page);

  // The publish package and its preflight report.
  await page.getByRole("link", { name: "Publish package" }).click();
  await expect(page.getByText(/never as passed/)).toBeVisible();
  await page.getByRole("button", { name: "Build the publish package" }).click();
  const open = page.getByRole("link", { name: "Open the preflight report" });
  await expect(open).toBeVisible({ timeout: 90_000 });
  await expect(
    page.getByRole("link", { name: "KDP-UPLOAD-STEPS.md" }),
  ).toBeVisible();
  await noSeriousA11y(page);
  const href = await open.getAttribute("href");
  await page.goto(href!);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: /Preflight report: Engine Manual/,
    }),
  ).toBeVisible();
  await expect(
    page.getByText(/does not guarantee that KDP will accept/),
  ).toBeVisible();
  await expect(
    page.getByRole("row", { name: /EPUBCheck.*unavailable/ }),
  ).toBeVisible();
  await expect(
    page.getByRole("row", { name: /Page count.*fail.*KDP allows 24–828/ }),
  ).toBeVisible();
});
