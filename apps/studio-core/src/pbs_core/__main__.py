"""`python -m pbs_core [command]`.

serve           Run the web API (and, with PBS_ROLE=all, the background worker). Default.
worker          Run only the background job and task worker (PBS_ROLE=worker on a server).
create-user     Create the studio's account from the server's command line (password on stdin).
reset-password  Set a new password for the account and sign out every session (password on stdin).
migrate         Bring the database to this version's schema (a snapshot is saved first), then exit.
status          What the studio holds and what the background worker is doing (--json for scripts).
check           Database integrity, schema, writable folders, free space. Exit code 1 on a problem.
verify-backup   Check a whole-studio backup archive without restoring it (exit code 1 if unusable).
"""

from __future__ import annotations

import argparse
import getpass
import json
import signal
import sys
import threading

from pbs_core.config import Settings


def _password(args: argparse.Namespace) -> str:
    if args.password_stdin or not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("New password: ")
    if getpass.getpass("Repeat it: ") != first:
        raise SystemExit("The two passwords differ. Nothing was changed.")
    return first


def serve(settings: Settings) -> None:
    import uvicorn

    from pbs_core.api.app import create_app

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=True,
        server_header=False,
        proxy_headers=bool(settings.trusted_proxies),
        forwarded_allow_ips=",".join(settings.trusted_proxies) or None,
    )


def worker(settings: Settings) -> None:
    from pbs_core.api.app import start_runner
    from pbs_core.context import build_context

    ctx = build_context(settings)
    runner, lock = start_runner(ctx)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    try:
        while not stop.wait(1.0):
            pass
    finally:
        runner.stop()  # type: ignore[attr-defined]
        lock.release()
        ctx.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pbs_core", description="Personal Book Studio Core")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the web API (default)")
    sub.add_parser("worker", help="run only the background worker")
    for name in ("create-user", "reset-password"):
        p = sub.add_parser(name)
        p.add_argument("username")
        p.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    sub.add_parser("migrate", help="migrate the database and exit")
    st = sub.add_parser("status", help="studio and background worker status")
    st.add_argument("--json", action="store_true")
    sub.add_parser("check", help="health checks; exit code 1 on a problem")
    vb = sub.add_parser("verify-backup", help="check a backup archive")
    vb.add_argument("archive")
    args = parser.parse_args(argv)
    settings = Settings()
    command = args.command or ("worker" if settings.role == "worker" else "serve")

    if command == "verify-backup":
        from pathlib import Path

        from pbs_core import ops

        try:
            print(json.dumps(ops.verify_archive(Path(args.archive)), indent=2))
        except (ops.ArchiveError, OSError, ValueError) as exc:  # tarfile and sqlite errors are ValueError/OSError
            raise SystemExit(f"Backup NOT usable: {exc}") from exc
        return
    if command in ("migrate", "status", "check"):
        from pbs_core import ops
        from pbs_core.context import build_context

        ctx = build_context(settings.model_copy(update={"log_console": False}))
        try:
            if command == "migrate":
                m = ctx.migration
                print(f"Schema {m.from_revision or 'new'} -> {m.to_revision}"
                      + (f" (snapshot {m.snapshot_path})" if m.snapshot_path else " (nothing to do)"))  # fmt: skip
            elif command == "status":
                st_out = ops.status(ctx)
                if args.json:
                    print(json.dumps(st_out, indent=2))
                else:
                    for k, v in st_out.items():
                        print(f"{k:28} {v}")
            else:
                problems, warnings = ops.check(ctx)
                for w in warnings:
                    print(f"WARNING: {w}")
                for problem in problems:
                    print(f"PROBLEM: {problem}")
                if problems:
                    raise SystemExit(1)
                print("OK: database, schema, folders and disk space")
        finally:
            ctx.close()
        return
    if command == "serve":
        serve(settings)
    elif command == "worker":
        worker(settings.model_copy(update={"role": "worker"}))
    else:
        from pbs_core.context import build_context
        from pbs_core.domain.errors import DomainError
        from pbs_core.services import auth

        ctx = build_context(settings.model_copy(update={"log_console": False}))
        try:
            if command == "create-user":
                auth.create_account(ctx, args.username, _password(args))
                print(f"Created the studio account {args.username.strip().lower()!r}. Sign in at the studio's address.")
            else:
                auth.reset_password(ctx, args.username, _password(args))
                print("Password changed. Every signed-in browser has been signed out.")
        except DomainError as exc:
            raise SystemExit(f"{exc.title} {exc.detail or ''}".strip()) from exc
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
