import { createServer, type IncomingMessage, type Server } from "node:http";
import type { AddressInfo } from "node:net";

/**
 * A loopback stand-in for Ollama's REST API (docs.ollama.com/api): /api/version, /api/tags,
 * /api/show and streaming NDJSON /api/chat. Deterministic, so the e2e run needs no real model.
 * An instruction containing "slowly" streams one word every 300 ms (for cancel/restart tests).
 */
export class OllamaStub {
  private server: Server | null = null;
  readonly chats: { model: string; messages: { role: string; content: string }[]; options: Record<string, unknown> }[] =
    [];
  port = 0;

  get url(): string {
    return `http://127.0.0.1:${this.port}`;
  }

  async start(): Promise<void> {
    this.server = createServer((req, res) => void this.handle(req, res));
    await new Promise<void>((resolve) => this.server!.listen(0, "127.0.0.1", resolve));
    this.port = (this.server.address() as AddressInfo).port;
  }

  async stop(): Promise<void> {
    this.server?.closeAllConnections();
    await new Promise((r) => this.server?.close(r));
  }

  private async handle(req: IncomingMessage, res: import("node:http").ServerResponse): Promise<void> {
    const body = await new Promise<string>((resolve) => {
      let data = "";
      req.on("data", (c) => (data += String(c)));
      req.on("end", () => resolve(data));
    });
    const json = (status: number, obj: unknown) => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(JSON.stringify(obj));
    };
    if (req.url === "/api/version") return json(200, { version: "0.12.6-stub" });
    if (req.url === "/api/tags")
      return json(200, {
        models: [{ name: "stub-writer:1b", model: "stub-writer:1b", details: { parameter_size: "1B", quantization_level: "Q4_K_M" } }],
      });
    if (req.url === "/api/show")
      return json(200, {
        capabilities: ["completion"],
        model_info: { "general.architecture": "stub", "stub.context_length": 8192 },
      });
    if (req.url === "/api/chat") {
      const parsed = JSON.parse(body);
      this.chats.push(parsed);
      const user = parsed.messages.at(-1)?.content ?? "";
      const slow = /slowly/.test(user);
      const words = "The night shift arrived at the engine house, lanterns swinging in the cold.".split(" ");
      res.writeHead(200, { "content-type": "application/x-ndjson" });
      for (const [i, w] of words.entries()) {
        if (res.destroyed) return;
        res.write(JSON.stringify({ model: parsed.model, message: { role: "assistant", content: (i ? " " : "") + w }, done: false }) + "\n");
        if (slow) await new Promise((r) => setTimeout(r, 300));
      }
      res.end(
        JSON.stringify({ model: parsed.model, message: { role: "assistant", content: "" }, done: true, done_reason: "stop",
                         prompt_eval_count: 180, eval_count: words.length }) + "\n",
      );
      return;
    }
    json(404, { error: "not found" });
  }
}
