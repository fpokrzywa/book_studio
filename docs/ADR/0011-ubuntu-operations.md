# ADR-0011: Ubuntu production deployment and operations (Phase 10)

Status: Accepted for Phase 10 (decisions P10-1 to P10-10 await the author's sign-off).
Date: 2026-11-23. Builds on ADR-0010; replaces its Caddy proxy (P9-9) with Nginx Proxy Manager.

## Context

Phase 10 asks for a production deployment on a self-hosted Ubuntu server behind Nginx Proxy Manager
(NPM). It needs durable storage, a way for NPM to reach the studio, local, remote and cloud AI, and
operations scripts: install, migrate, validate, update, back up, restore, roll back, logs and job
monitoring. It also asks for an end-to-end test, without adding infrastructure the architecture does
not need.

## Decisions

**P10-1 Services: `app`, `worker`, optional `ollama`. No separate frontend server, database, Redis
or broker.**
- Core already serves the built UI (P9-13), so a separate frontend server would only add a hop.
- The durable job queue (AI jobs and background tasks) lives in SQLite, with claims made in one
  transaction and an OS lock that allows one worker, so a broker would add nothing.
- PostgreSQL would mean migrating the data model and the FTS5 search index, and running a second
  stateful service, for one author on one host. ADR-0010 P9-2 still holds.

**P10-2 Nginx Proxy Manager reaches the app over a shared external Docker network**
(`PBS_PROXY_NETWORK`, default `npm_proxy`).
- The app joins it with the alias `book-studio-app`, unique on a network other stacks may share, and
  publishes no host port.
- For NPM on another machine, `compose.publish.yaml` publishes Core on one chosen address.
- The Caddy service from Phase 09 is removed.

**P10-3 Trusted proxies by subnet.** NPM's container address changes when it is recreated, so Core
trusts `X-Forwarded-*` from the shared network's subnet (uvicorn accepts networks). `install.sh`
reads the subnet and refreshes it on every run; `validate.sh` fails when it no longer matches.
Containers on that network can reach the studio's HTTP port, but every request still needs a session.

**P10-4 Host folders (bind mounts) for all data,** under `/srv/book-studio`: data, backups, secrets
and Ollama models.
- No Docker command deletes them, `docker compose down -v` included, so container recreation and
  image updates are safe by construction.
- The backup scripts can work on plain files.
- The data folder is owned by the image's user (10001) with mode 700. The master key is mode 400,
  outside the data folder.

**P10-5 Cold, verified backups.** `backup.sh` stops app and worker for the seconds the tar takes, so
the database, its WAL and the files match. It verifies the archive with the running image
(`python -m pbs_core verify-backup`: safe member names, integrity check, schema, counts) and writes a
checksum and manifest. Hot backups were rejected: they could pair a database with files from a
different moment.

**P10-6 Restore and rollback never delete.** The current data folder is moved to
`data.pre-restore-<time>`. Updates build a new image tag next to the old one and take a pre-update
backup. Rollback means old image plus pre-update backup, because migrations are forward-only.

**P10-7 Operations commands in Core** (`migrate`, `status`, `check`, `verify-backup`), so the shell
scripts only orchestrate Docker and need no Python packages on the host.

**P10-8 Remote Ollama.** `PBS_LOCAL_AI_HOSTS` now also takes IPv4 addresses (another computer on the
LAN). Native Ollama on the host is reached as `host.docker.internal` (`host-gateway`). These hosts
count as local: allowed in local-only mode, never billed. The operator, not the browser, names them.

**P10-9 Operator switch for cloud AI.** `PBS_ALLOW_CLOUD=false` forces local-only whatever the in-app
setting says:
- the privacy endpoint refuses `cloud_allowed` (409, `cloud_disabled_by_operator`);
- every cloud permit is refused before a connection;
- AI settings shows the switch as off and explains why.

**P10-10 Validation uses a real local model.** The end-to-end script runs the AI step against
`qwen2.5:0.5b` in the Ollama container rather than the test model, which production hides. That way
the worker, the egress gate and the proposal-and-approval flow are exercised as deployed. The edit's
quality is not judged.

## Consequences

* `deploy/` now holds:
  - `compose.yaml`, `compose.publish.yaml`, `.env.example` and the `Dockerfile`;
  - `scripts/`: install, update, backup, restore, rollback, validate, status, diagnose and a shared
    `common.sh`;
  - `validation/`: a manuscript generator and the e2e script with its runner.
* `deploy/Caddyfile` and `deploy/make-secret.sh` are removed (install.sh creates the key).
* Not covered: Let's Encrypt issuance, VPN access, a physical or cloud Ubuntu host (the test system
  was Ubuntu 24.04 in a privileged container), Ollama installed natively, and cloud providers with
  real keys.
