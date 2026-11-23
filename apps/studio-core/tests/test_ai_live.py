"""Opt-in checks against real providers. Never run by default.

* Ollama smoke test: runs only when an Ollama server answers on 127.0.0.1:11434 and
  PBS_OLLAMA_MODEL names a pulled model (marker `ollama`).
* Cloud checks: run only with PBS_LIVE_TESTS=1 and PBS_<KIND>_API_KEY set (marker `live`).
  They send one tiny prompt and may cost a fraction of a cent.
"""

from __future__ import annotations

import os
import socket

import pytest

from pbs_core.providers.base import ChatMessage, GenRequest
from pbs_core.providers.egress import EgressPermit


def _ollama_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.ollama
@pytest.mark.skipif(
    not _ollama_up() or not os.environ.get("PBS_OLLAMA_MODEL"), reason="no local Ollama / PBS_OLLAMA_MODEL"
)
def test_ollama_smoke() -> None:
    from pbs_core.providers.ollama import OllamaAdapter

    a = OllamaAdapter(EgressPermit("ollama", cloud_allowed=False))
    assert a.health().ok
    model = os.environ["PBS_OLLAMA_MODEL"]
    assert model in [m.name for m in a.list_models()]
    out = a.stream_chat(
        GenRequest(
            model=model, system="Reply briefly.", messages=[ChatMessage("user", "Say hello.")], max_output_tokens=20
        ),
        lambda _: None,
        lambda: False,
    )
    assert out.text.strip() and out.usage.reported


def test_live_cloud_checks_are_a_separate_opt_in_command() -> None:
    """Cloud providers are never called from the test suite (the network guard forbids it).

    Run `uv run python -m pbs_core.live_check --kind <kind> --model <id>` with PBS_<KIND>_API_KEY set.
    """
    from pbs_core import live_check

    assert callable(live_check.main)
