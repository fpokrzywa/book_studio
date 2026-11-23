import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test, openAiPanel } from "./fixtures";
import { OllamaStub } from "./ollama-stub";

async function noSeriousA11y(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
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

async function addLocalModel(page: Page, stub: OllamaStub) {
  await page.goto("/ai-settings");
  await expect(
    page.getByRole("heading", { level: 1, name: "AI settings" }),
  ).toBeVisible();
  await expect(page.getByLabel(/Local only/)).toBeChecked();
  await page.getByLabel("Provider", { exact: true }).selectOption("ollama");
  await page.getByLabel("Address (optional)").fill(stub.url);
  await page.getByRole("button", { name: "Add provider" }).click();
  const card = page.getByRole("article", { name: "Ollama (local)" });
  await card.getByRole("button", { name: "Test connection" }).click();
  await expect(
    card.getByText(/Working: Ollama 0.12.6-stub is running locally/),
  ).toBeVisible();
  await card.getByRole("button", { name: "Find models" }).click();
  await card.getByText(/Models \(1\)/).click();
  await expect(
    card.getByRole("rowheader", { name: /stub-writer:1b/ }),
  ).toBeVisible();
  await noSeriousA11y(page);
}

async function bookWithChapter(page: Page) {
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("The Quiet Engine");
  await page.getByLabel("Kind of book").selectOption("fiction");
  await page.getByRole("button", { name: "Create book" }).click();
  await page.getByLabel("New chapter title").fill("Chapter One");
  await page.getByRole("button", { name: "Add chapter" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Chapter One" }),
  ).toBeVisible();
  await page.getByLabel("Plain text editor").check();
  await page
    .getByLabel("Chapter text (Markdown)")
    .fill("The engine room was quiet.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/^Saved as revision 1/)).toBeVisible();
}

async function ask(page: Page, instruction: string) {
  const panel = page.getByRole("region", { name: "AI assist" });
  await openAiPanel(page);
  await panel.getByLabel("Model").selectOption({ label: "stub-writer:1b" });
  await expect(
    panel.getByText("On this computer", { exact: false }).first(),
  ).toBeVisible();
  await panel.getByLabel("What should it do?").fill(instruction);
  await expect(panel.getByText(/no API charge/i)).toBeVisible();
  await panel.getByRole("button", { name: "Ask" }).click();
  return panel;
}

test("Phase 03 acceptance: choose a local model, draft into review, accept as a revision, zero cloud calls", async ({
  page,
  core,
}) => {
  const stub = new OllamaStub();
  await stub.start();
  try {
    await addLocalModel(page, stub);
    await bookWithChapter(page);

    const panel = await ask(
      page,
      "One paragraph where the night shift arrives.",
    );
    const card = panel.getByRole("article", {
      name: /Draft by stub-writer:1b/,
    });
    await expect(card).toBeVisible({ timeout: 15_000 });
    await expect(card.getByLabel(/Suggested text/)).toHaveValue(
      "The night shift arrived at the engine house, lanterns swinging in the cold.",
    );
    // Review first: the chapter itself is untouched.
    await expect(page.getByLabel("Chapter text (Markdown)")).toHaveValue(
      "The engine room was quiet.",
    );
    await noSeriousA11y(page);

    // The model only ever saw this chapter, inside the untrusted-data envelope.
    const sent = stub.chats.at(-1)!;
    expect(sent.model).toBe("stub-writer:1b");
    expect(sent.messages.at(-1)!.content).toMatch(
      /<pbs-data-[0-9a-f]+ label="chapter text so far">/,
    );
    expect(sent.messages.at(-1)!.content).toContain(
      "The engine room was quiet.",
    );

    await card
      .getByRole("button", { name: "Accept as a new revision" })
      .click();
    await expect(page.getByText(/^Saved as revision 2/)).toBeVisible();
    await expect(page.getByLabel("Chapter text (Markdown)")).toHaveValue(
      "The engine room was quiet.\n\nThe night shift arrived at the engine house, lanterns swinging in the cold.\n",
    );
    await page.getByRole("button", { name: "History" }).click();
    await expect(
      page.getByRole("dialog").getByText("AI-generated (accepted)"),
    ).toBeVisible();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Close" })
      .click();

    // Status center: done, local, no charge. Local-only mode made zero internet requests.
    await page.getByRole("link", { name: "AI jobs" }).click();
    await expect(
      page.getByRole("rowheader", { name: /Draft with stub-writer:1b/ }),
    ).toBeVisible();
    await expect(page.getByText("No charge")).toBeVisible();
    await noSeriousA11y(page);
    await page.getByRole("link", { name: "AI settings" }).click();
    await expect(
      page.getByText(/Requests sent to the internet since Core started/),
    ).toContainText("none");
    expect(core.output).not.toMatch(
      /api\.openai\.com|api\.anthropic\.com|googleapis|api\.groq|api\.x\.ai/,
    );
  } finally {
    await stub.stop();
  }
});

test("cancel, retry and a Core crash mid-job never corrupt the chapter or apply twice", async ({
  page,
  core,
}) => {
  const stub = new OllamaStub();
  await stub.start();
  try {
    await addLocalModel(page, stub);
    await bookWithChapter(page);
    const chapterUrl = page.url();

    // Cancel while text is streaming: nothing is proposed, the chapter is unchanged.
    let panel = await ask(page, "Write slowly please.");
    await expect(panel.getByText(/Receiving text/)).toBeVisible({
      timeout: 10_000,
    });
    await panel.getByRole("button", { name: "Cancel" }).click();
    await expect(panel.getByText(/Cancelled by the author/)).toBeVisible({
      timeout: 10_000,
    });
    await expect(panel.getByRole("article")).toHaveCount(0);

    // Retry it, then crash Core while it streams. After restart it runs again exactly once.
    await panel.getByRole("button", { name: "Retry" }).click();
    await expect(panel.getByText(/Receiving text/)).toBeVisible({
      timeout: 10_000,
    });
    await core.restart();
    await page.goto(chapterUrl);
    panel = page.getByRole("region", { name: "AI assist" });
    await expect(
      page.getByRole("heading", { level: 1, name: "Chapter One" }),
    ).toBeVisible();
    // The panel remembers it was open; open it only if it is not.
    await openAiPanel(page);
    await expect(panel.getByRole("article")).toHaveCount(1, {
      timeout: 30_000,
    });
    await expect(page.getByLabel("Chapter text (Markdown)")).toHaveValue(
      "The engine room was quiet.",
    );

    // Double-clicking Accept still creates exactly one revision.
    const accept = panel.getByRole("button", {
      name: "Accept as a new revision",
    });
    await accept.dblclick();
    await expect(page.getByText(/^Saved as revision 2/)).toBeVisible();
    await page.getByRole("button", { name: "History" }).click();
    await expect(
      page.getByRole("dialog").getByText("AI-generated (accepted)"),
    ).toHaveCount(1);
  } finally {
    await stub.stop();
  }
});
