import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";

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

/** Call Core the same way the app does (same origin, through the UI's proxy). */
async function api<T = Record<string, unknown>>(
  page: Page,
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  return page.evaluate(
    async ({ method, path, body }) => {
      const state = await (await fetch("/api/auth/state")).json();
      const headers: Record<string, string> = {
        "X-PBS-CSRF": state.csrf_token ?? "",
      };
      if (body !== undefined) headers["content-type"] = "application/json";
      const res = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await res.text();
      if (!res.ok) throw new Error(`${method} ${path}: ${res.status} ${text}`);
      return text ? JSON.parse(text) : null;
    },
    { method, path, body },
  ) as Promise<T>;
}

async function book(
  page: Page,
  title: string,
  text: string,
): Promise<{ pid: string; cid: string }> {
  const p = await api<{ id: string }>(page, "POST", "/api/projects", {
    title,
    project_type: "fiction",
  });
  const c = await api<{ id: string }>(
    page,
    "POST",
    `/api/projects/${p.id}/chapters`,
    { title: "Chapter One" },
  );
  await api(page, "PUT", `/api/projects/${p.id}/chapters/${c.id}/content`, {
    source_md: text,
    expected_head_no: 0,
  });
  return { pid: p.id, cid: c.id };
}

test("Phase 08 acceptance: shared canon, a contradiction resolved by the author, and a linked translation", async ({
  page,
  core,
}) => {
  void core;
  test.setTimeout(180_000);
  await page.goto("/");
  const b1 = await book(
    page,
    "The Salt Road",
    "Mara looked up. Mara's green eyes caught the lamp.\n",
  );
  const b2 = await book(
    page,
    "The Iron Tide",
    "Years later, Mara turned. Mara's brown eyes were wet.\n",
  );

  // A series of two books.
  await page.getByRole("link", { name: "Series", exact: true }).click();
  await page.getByLabel("Series title").fill("Tides of Salt");
  await page.getByRole("button", { name: "Create series" }).click();
  await page.getByRole("link", { name: "Tides of Salt" }).click();
  for (const t of ["The Salt Road", "The Iron Tide"]) {
    await page.getByLabel("Add a book").selectOption({ label: t });
    await page.getByRole("button", { name: "Add to series" }).click();
    await expect(page.getByRole("link", { name: t })).toBeVisible();
  }
  await noSeriousA11y(page);

  // Canon: Mara has green eyes (author-approved).
  await page.getByRole("link", { name: /^Story bible/ }).click();
  await page.getByLabel("Name", { exact: true }).fill("Mara");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Mara/ })).toBeVisible();
  await page.getByLabel("Fact", { exact: true }).fill("eye colour");
  await page.getByLabel("Value", { exact: true }).fill("grey");
  await page.getByRole("button", { name: "Add fact" }).click();
  // Modify canon: correct the value; the old one is kept as an earlier value.
  const facts = page.getByRole("table", { name: "Facts about Mara" });
  await facts.getByRole("button", { name: "Edit" }).click();
  await facts.getByLabel("New value for eye colour").fill("green");
  await facts.getByRole("button", { name: "Save" }).click();
  await expect(facts.getByText("green", { exact: true })).toBeVisible();
  await expect(page.getByText("Earlier values (1)")).toBeVisible();
  await noSeriousA11y(page);

  // The intentional contradiction in book 2 is found and linked to its passage.
  await page.getByRole("link", { name: /^Continuity review/ }).click();
  await page.getByRole("button", { name: "Run the check" }).click();
  const card = page
    .getByRole("listitem")
    .filter({ hasText: "Mara's brown eyes were wet." });
  await expect(card).toBeVisible();
  await expect(
    card.getByRole("link", { name: /open the passage/ }),
  ).toHaveAttribute(
    "href",
    new RegExp(`/projects/${b2.pid}/chapters/${b2.cid}\\?select=\\d+-\\d+`),
  );
  await noSeriousA11y(page);
  await card
    .getByLabel("Note for your decision (optional)")
    .fill("Contact lenses.");
  await card.getByRole("button", { name: "Intended, leave it" }).click();
  await expect(
    page.getByText(/No open contradictions with canon/),
  ).toBeVisible();

  // Running the check again keeps the decision.
  await page.getByRole("button", { name: "Run the check" }).click();
  await expect(
    page.getByText(/No open contradictions with canon/),
  ).toBeVisible();
  await page.getByLabel("Show questions you already resolved").check();
  await expect(card.getByText("Intended (left as written)")).toBeVisible();
  await expect(card.getByText("Contact lenses.")).toBeVisible();

  // The passage link opens the chapter (text editing works without the map or the review).
  await page.getByRole("link", { name: /open the passage/ }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Chapter One" }),
  ).toBeVisible();

  // Translation: approve book 1's chapter, make a French edition, translate with the test model.
  await api(page, "POST", "/api/ai/providers", { kind: "mock" });
  await api(page, "PATCH", `/api/projects/${b1.pid}/chapters/${b1.cid}`, {
    status: "approved",
  });
  const before = await api<{ source_md: string; revision_no: number }>(
    page,
    "GET",
    `/api/projects/${b1.pid}/chapters/${b1.cid}/content`,
  );
  await page.goto(`/projects/${b1.pid}/translations`);
  await page.getByLabel("Language code").fill("fr");
  await page.getByRole("button", { name: "Create edition" }).click();
  await expect(
    page.getByRole("heading", { name: /The Salt Road.*fr/ }),
  ).toBeVisible();
  await page
    .getByLabel("AI provider for translating")
    .selectOption({ index: 1 });
  await page.getByLabel("Model").selectOption("mock-writer");
  await page.getByRole("button", { name: "Translate", exact: true }).click();
  await expect(
    page.getByText("Translation waiting for your review"),
  ).toBeVisible({ timeout: 30_000 });
  await noSeriousA11y(page);

  // The original is untouched; both chapters show their language links.
  const after = await api<{ source_md: string; revision_no: number }>(
    page,
    "GET",
    `/api/projects/${b1.pid}/chapters/${b1.cid}/content`,
  );
  expect(after.source_md).toBe(before.source_md);
  expect(after.revision_no).toBe(before.revision_no);
  await page.goto(`/projects/${b1.pid}/chapters/${b1.cid}`);
  const langs = page.getByRole("region", { name: "Other languages" });
  await expect(langs.getByText("fr", { exact: true })).toBeVisible();
  await langs.getByRole("link").first().click();
  await expect(
    page
      .getByRole("region", { name: "Other languages" })
      .getByText(/Translated from/),
  ).toBeVisible();
});

test("Phase 08: narration and transcription degrade gracefully and stay local", async ({
  page,
  core,
}) => {
  void core;
  await page.goto("/");
  const b = await book(page, "Quiet Book", "It was late. The tide turned.\n");
  await page.goto(`/projects/${b.pid}/narration`);
  await expect(
    page.getByText(/Narration is optional and off by default/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Prepare script" }).click();
  await page.getByRole("button", { name: "Show script" }).click();
  await expect(
    page.getByText("Chapter One. It was late. The tide turned."),
  ).toBeVisible();
  // Off by default: asking for audio explains why nothing ran.
  await page
    .getByRole("button", { name: "Make audio for the next parts" })
    .click();
  await expect(page.getByText(/Narration is off for this book/)).toBeVisible();
  await noSeriousA11y(page);

  await page.goto(`/projects/${b.pid}/recordings`);
  await expect(page.getByRole("button", { name: "Import" })).toBeDisabled();
  await noSeriousA11y(page);
  const status = await api<{
    privacy_mode: string;
    speech: { kind: string; available: boolean; local: boolean }[];
  }>(page, "GET", "/api/media/status");
  expect(status.privacy_mode).toBe("local_only");
  expect(status.speech.filter((s) => !s.local).every((s) => !s.available)).toBe(
    true,
  );
});
