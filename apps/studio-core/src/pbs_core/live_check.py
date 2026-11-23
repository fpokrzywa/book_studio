"""Opt-in live check of one real provider: connection, model list, one tiny generation.

    uv run python -m pbs_core.live_check --kind openai --model <model-id>

The key comes from PBS_<KIND>_API_KEY. This sends a short fixed prompt (no manuscript text) to the
provider and may cost a fraction of a cent. It is never run by the automated test suite.
"""

from __future__ import annotations

import argparse
import sys

from pbs_core.providers.base import ChatMessage, GenRequest, ProviderError
from pbs_core.providers.egress import EgressBlockedError, EgressPermit
from pbs_core.security.secrets import env_key


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", required=True, choices=["ollama", "openai", "anthropic", "gemini", "groq", "xai"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default=None, help="Ollama only")
    args = ap.parse_args(argv)

    permit = EgressPermit(args.kind, cloud_allowed=args.kind != "ollama")
    key = env_key(args.kind)
    try:
        if args.kind == "ollama":
            from pbs_core.providers.ollama import DEFAULT_BASE_URL, OllamaAdapter

            adapter: object = OllamaAdapter(permit, args.base_url or DEFAULT_BASE_URL)
        elif args.kind == "anthropic":
            from pbs_core.providers.anthropic_adapter import AnthropicAdapter

            adapter = AnthropicAdapter(key, permit)
        elif args.kind == "gemini":
            from pbs_core.providers.gemini import GeminiAdapter

            adapter = GeminiAdapter(key, permit)
        else:
            from pbs_core.providers.openai_compat import OpenAICompatAdapter

            adapter = OpenAICompatAdapter(args.kind, key, permit)
        print("health:", adapter.health().message)  # type: ignore[attr-defined]
        models = adapter.list_models()  # type: ignore[attr-defined]
        print(f"models: {len(models)} listed; requested model present: {args.model in [m.name for m in models]}")
        out = adapter.stream_chat(  # type: ignore[attr-defined]
            GenRequest(
                args.model,
                "Reply with one short sentence.",
                [ChatMessage("user", "Say hello to a writer.")],
                max_output_tokens=40,
            ),
            lambda _: None,
            lambda: False,
        )
        print("reply:", out.text.strip()[:200])
        print(f"usage: {out.usage.input_tokens} in / {out.usage.output_tokens} out (reported={out.usage.reported})")
        return 0
    except (ProviderError, EgressBlockedError) as exc:
        print("FAILED:", getattr(exc, "code", "blocked"), str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
