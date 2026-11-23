# Deployment verification

What was verified on Ubuntu (2026-11-23), how, and the exact commands to repeat it on your own server.

## 1. Environment

| | |
|---|---|
| Operating system | Ubuntu 24.04.5 LTS userland, inside a privileged container on the Windows 11 development machine; its own Docker Engine |
| Docker | Engine 29.10.0, Compose v5.8.0 |
| Reverse proxy | Nginx Proxy Manager 2.17.1 on the shared `npm_proxy` network; proxy host `books.test` → `http://book-studio-app:8765`, Force SSL, the four Advanced lines (DEPLOYMENT §3.2) |
| Certificate | Custom certificate from a private test CA (stands in for Let's Encrypt) |
| AI | Ollama 0.40.17 container (`--profile local-ai`) with `qwen2.5:0.5b` |
| Studio image | built by `install.sh`, then updated by `update.sh` to the latest code (`8e9383e4eabd`) |

**Not a physical or cloud server** (KNOWN_ISSUES 2): repeat §3 on yours.

## 2. Results

| Check | How | Result |
|---|---|---|
| Compose configuration valid | `docker compose … config --quiet` | PASS |
| Containers healthy; restart policy | `compose ps`; the box was stopped and started like a reboot | PASS: app, worker, ollama and NPM came back by themselves; app and worker healthy |
| Database migrations | `install.sh` (0 → 0010), `update.sh` ×3, `python -m pbs_core migrate` | PASS: snapshot taken first; "nothing to do" when current |
| Persistent data | bind mounts under `/srv/book-studio`; restart, full container recreation (`down` + `up -d`), three image updates, a rollback | PASS: every revision hash, asset, export and original identical each time |
| Worker executes jobs | AI revision and DOCX/EPUB/PDF export in the worker | PASS |
| Interrupted AI job | worker killed (`docker kill`) mid-generation, then started | PASS: the job re-ran (attempt 2) and succeeded; exactly 1 suggestion; chapter unchanged until approval |
| Interrupted export task | worker killed after queueing a PDF build | NOT EXERCISED on Ubuntu: the 7-page PDF finished before the kill. Recovery is covered by `test_web.py::test_task_left_running_by_a_crash_is_retried_then_interrupted` |
| Web UI without a desktop runtime | browser UI served by Core through NPM; Playwright drives Chromium against Core (19 specs) | PASS |
| NPM and HTTPS | `validate.sh --url https://books.test --cacert ca.pem` | PASS: `/healthz` through NPM, HTTP → HTTPS redirect, HSTS and CSP headers |
| Authentication enforced | e2e and validate: anonymous API 401; wrong password 401; write without CSRF 403; every one of 219 API operations needs a session (`test_web.py`) | PASS |
| Nothing exposed | `ss -tln` on the host; `docker port` | PASS: only NPM (80/443, admin 81 on 127.0.0.1). Core and Ollama unreachable from the host; worker and Ollama publish nothing; the `backend` network is internal (no internet) |
| Secrets not in logs | container logs and `core.jsonl` searched for the account password, master key and setup code | PASS: 0 occurrences; 0 tracebacks; 0 error-level lines |
| Backup | `backup.sh` | PASS: verified archive (integrity, schema, counts), checksum, manifest |
| Restore | `restore.sh` (in e2e) | PASS: a book created after the backup is gone; everything else identical |
| **Restore into an isolated environment** | backup copied to a separate Compose project (`PBS_PROJECT_NAME=book-studio-isolated`, own data folder, own network, same master key); restored as onto a new server | PASS: production and isolated copy have **identical** book list, 18 revision hashes, 4 assets and 4 original source files (fingerprints `130eb6f8…`, `f78131f1…`); production stayed healthy |
| Update | `update.sh` (×3, once appending to a log as cron would) | PASS: pre-update backup, new image beside the old, migrate, validate; the appended log is intact (0 NUL bytes) |
| Rollback | `rollback.sh --yes` | PASS: previous image and pre-update backup; post-update data kept aside |
| Remote Ollama | second Ollama on the system's own address, added to `PBS_LOCAL_AI_HOSTS` | PASS: connection test and model list; an address not on the list refused (422) |
| Cloud switch | `PBS_ALLOW_CLOUD=false` | PASS: allowing cloud refused (409); status local-only |
| Other Docker applications | — | NPM's container, network and volumes were only connected to (`docker network connect`), never changed; no other stack was touched |

## 3. Repeat it on your server

Run from the checkout (`cd /opt/book-studio`) with your domain. Each command prints PASS/FAIL lines or
exits non-zero on failure.

```sh
# Configuration, containers, migrations, exposure, permissions, HTTPS through NPM
sudo docker compose -f deploy/compose.yaml --env-file deploy/.env config --quiet && echo "compose OK"
sudo deploy/scripts/validate.sh --url https://books.example.com
sudo ss -tln                       # expect only your proxy's ports (80/443) and nothing on 8765 or 11434
sudo deploy/scripts/status.sh      # jobs, tasks, worker heartbeat

# Full workflow: import, AI edit with review, exports, restart, recreate, backup, restore
read -rsp 'Studio password: ' PW; echo; printf '%s' "$PW" | sudo install -m 600 /dev/stdin /root/pbs-password; unset PW
sudo deploy/validation/run_e2e.sh --url https://books.example.com --username author \
     --password-file /root/pbs-password --ollama-url http://ollama:11434 --model qwen2.5:0.5b
sudo shred -u /root/pbs-password

# Secrets must not appear in logs (expect 0)
sudo docker compose -f deploy/compose.yaml --env-file deploy/.env logs app worker | grep -c -F "$(sudo cat /srv/book-studio/secrets/pbs_master_key)"
```

`run_e2e.sh` adds a book named "Validation <date>". It stops the studio for a few seconds twice (backup
and restore) and keeps the pre-restore data aside; nothing is deleted. **Do not use the studio while it
runs**: its last step restores the backup it took a minute earlier, so anything saved in between is set
aside in `data.pre-restore-*`. Without a local model, give
`--ollama-url` and `--model` for one you have. The AI step needs a model.
