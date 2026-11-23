import { spawn, type ChildProcess } from "node:child_process";
import {
  chmodSync,
  existsSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import path from "node:path";
import { test as base, expect, type Page } from "@playwright/test";

const ROOT = path.resolve(__dirname, "..");
const PYTHON = [
  path.join(ROOT, "apps", "studio-core", ".venv", "Scripts", "python.exe"),
  path.join(ROOT, "apps", "studio-core", ".venv", "bin", "python"),
].find((p) => existsSync(p));

export class Core {
  private proc: ChildProcess | null = null;
  readonly workspace = process.env.PBS_E2E_WORKSPACE as string;
  readonly port = Number(process.env.PBS_E2E_CORE_PORT);
  private readonly uiPort = Number(process.env.PBS_E2E_UI_PORT);
  output = "";

  async start(): Promise<void> {
    if (!PYTHON)
      throw new Error("Core venv not found; run scripts/setup first");
    this.proc = spawn(PYTHON, ["-m", "pbs_core"], {
      env: {
        ...process.env,
        PBS_ENV: "test",
        PBS_WORKSPACE: this.workspace,
        PBS_PORT: String(this.port),
        PBS_UI_ORIGINS: JSON.stringify([
          `http://127.0.0.1:${this.uiPort}`,
          `http://localhost:${this.uiPort}`,
        ]),
        PBS_LOG_CONSOLE: "false",
        PBS_SECRET_BACKEND: "memory", // never touch the OS credential store from tests
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.proc.stdout?.on("data", (d) => (this.output += String(d)));
    this.proc.stderr?.on("data", (d) => (this.output += String(d)));
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (this.proc.exitCode !== null)
        throw new Error(`Core exited early:\n${this.output}`);
      try {
        const res = await fetch(`http://127.0.0.1:${this.port}/healthz`);
        if (res.ok) return;
      } catch {
        /* not up yet */
      }
      await new Promise((r) => setTimeout(r, 200));
    }
    throw new Error(`Core did not become healthy:\n${this.output}`);
  }

  /** Hard kill (TerminateProcess / SIGKILL): simulates a crash, not a graceful shutdown. */
  async kill(): Promise<void> {
    const proc = this.proc;
    if (!proc || proc.exitCode !== null) return;
    const exited = new Promise((r) => proc.once("exit", r));
    proc.kill("SIGKILL");
    await exited;
    this.proc = null;
  }

  async restart(): Promise<void> {
    await this.kill();
    await this.start();
  }

  /** The one-time code Core writes while the studio has no account (never logged). */
  setupCode(): string {
    return readFileSync(
      path.join(this.workspace, "runtime", "setup-code.txt"),
      "utf8",
    ).trim();
  }

  wipe(): void {
    makeWritable(this.workspace); // preserved originals are read-only on disk
    rmSync(this.workspace, {
      recursive: true,
      force: true,
      maxRetries: 10,
      retryDelay: 200,
    });
  }
}

function makeWritable(dir: string): void {
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) makeWritable(full);
    else chmodSync(full, 0o666);
  }
}

export const OWNER = "author";
export const PASSWORD = "e2e only password 42"; // test-only account in a throwaway workspace

/** Create the studio account through the real setup endpoint; the browser keeps the session cookie. */
export async function signUp(page: Page, core: Core): Promise<void> {
  const res = await page.request.post("/api/auth/setup", {
    headers: { "X-PBS-CSRF": "1" },
    data: { username: OWNER, password: PASSWORD, setup_code: core.setupCode() },
  });
  expect(res.status(), await res.text()).toBe(200);
}

export const test = base.extend<{ core: Core; signedIn: boolean }>({
  signedIn: [true, { option: true }],
  core: async ({ page, signedIn }, use) => {
    const core = new Core();
    core.wipe();
    await core.start();
    if (signedIn) await signUp(page, core);
    await use(core);
    await core.kill();
  },
});

/**
 * Open the editor's AI assist panel. The panel remembers whether it was open, so act on the toggle's
 * own aria-expanded once the page has rendered; checking the panel before render would close it.
 */
export async function openAiPanel(page: Page) {
  const toggle = page.getByRole("button", { name: /^AI assist/ });
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute("aria-expanded")) !== "true")
    await toggle.click();
  const panel = page.getByRole("region", { name: "AI assist" });
  await expect(panel).toBeVisible();
  return panel;
}

/**
 * Add the built-in test model in AI settings and wait until Core has saved it. Navigating away
 * straight after the click can cancel the request, leaving no model to choose later.
 */
export async function addMockProvider(page: Page) {
  await page.getByLabel("Provider", { exact: true }).selectOption("mock");
  const saved = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname === "/api/ai/providers",
  );
  await page.getByRole("button", { name: "Add provider" }).click();
  expect((await saved).status()).toBe(201);
}

export { expect };
