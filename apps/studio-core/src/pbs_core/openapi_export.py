"""Print the OpenAPI document without starting a server or touching a workspace."""

from __future__ import annotations

import json
import sys

from pbs_core.api.app import create_app


def openapi_json() -> str:
    doc = create_app(initialize=False).openapi()
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    data = openapi_json().encode("utf-8")
    if len(sys.argv) > 1:  # write to a file (avoids console encoding issues on Windows)
        with open(sys.argv[1], "wb") as fh:
            fh.write(data)
    else:
        sys.stdout.buffer.write(data)
