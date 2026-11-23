import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect, OWNER, PASSWORD, test } from "./fixtures";

test.use({ signedIn: false });

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

test("Phase 09: first visit creates the account, sign out and in, session survives a Core restart", async ({
  page,
  core,
}) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Create your studio account" }),
  ).toBeVisible();
  await noSeriousA11y(page);
  // Nothing of the studio is reachable before the account exists.
  const blocked = await page.request.get("/api/projects");
  expect(blocked.status()).toBe(401);

  await page.getByLabel("Setup code").fill("not the code");
  await page.getByLabel("Username").fill(OWNER);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByLabel("Repeat the password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("That setup code is not right.")).toBeVisible();
  await page.getByLabel("Setup code").fill(core.setupCode());
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(
    page.getByRole("heading", { name: "No books yet" }),
  ).toBeVisible();

  // Write something through the normal UI (every write carries the CSRF token).
  await page.goto("/new");
  await page.getByLabel("Title", { exact: true }).fill("Signed In Book");
  await page.getByRole("button", { name: "Create book" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Signed In Book" }),
  ).toBeVisible();

  // The session is stored by Core, so a restart does not sign the browser out.
  await core.restart();
  await page.goto("/");
  await expect(page.getByText("Signed In Book").first()).toBeVisible();

  // Sign out from Account, then sign back in.
  await page.getByRole("link", { name: "Account" }).click();
  await expect(page.getByRole("heading", { name: "Account" })).toBeVisible();
  await noSeriousA11y(page);
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  expect((await page.request.get("/api/projects")).status()).toBe(401);
  await page.getByLabel("Username").fill(OWNER);
  await page.getByLabel("Password").fill("wrong password!!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByText("That username and password do not match."),
  ).toBeVisible();
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Account" })).toBeVisible(); // back where the user was
  await page.goto("/");
  await expect(page.getByText("Signed In Book").first()).toBeVisible();

  // A cross-site style request without the CSRF token is refused even with the cookie.
  const forged = await page.request.post("/api/projects", {
    data: { title: "x", project_type: "fiction" },
  });
  expect(forged.status()).toBe(403);
});
