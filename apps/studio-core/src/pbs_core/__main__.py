"""`python -m pbs_core` - run Core on the loopback interface."""

from __future__ import annotations

import uvicorn

from pbs_core.api.app import create_app
from pbs_core.config import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=True,
        server_header=False,
    )


if __name__ == "__main__":
    main()
