import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import path from "node:path";
import { test as base, expect } from "@playwright/test";

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
    if (!PYTHON) throw new Error("Core venv not found; run scripts/setup first");
    this.proc = spawn(PYTHON, ["-m", "pbs_core"], {
      env: {
        ...process.env,
        PBS_ENV: "test",
        PBS_WORKSPACE: this.workspace,
        PBS_PORT: String(this.port),
        PBS_UI_ORIGINS: JSON.stringify([`http://127.0.0.1:${this.uiPort}`, `http://localhost:${this.uiPort}`]),
        PBS_LOG_CONSOLE: "false",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.proc.stdout?.on("data", (d) => (this.output += String(d)));
    this.proc.stderr?.on("data", (d) => (this.output += String(d)));
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if (this.proc.exitCode !== null) throw new Error(`Core exited early:\n${this.output}`);
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

  wipe(): void {
    rmSync(this.workspace, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
}

export const test = base.extend<{ core: Core }>({
  core: async ({}, use) => {
    const core = new Core();
    core.wipe();
    await core.start();
    await use(core);
    await core.kill();
  },
});

export { expect };
