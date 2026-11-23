# Operating Personal Book Studio on Ubuntu

Everything here assumes the install in `docs/DEPLOYMENT.md`, run from the checkout
(`cd /opt/book-studio`) with `sudo`. None of these scripts removes Docker volumes or data folders.
Restore and rollback move the current data aside instead of deleting it.

| Task | Command |
|---|---|
| Is everything healthy? | `sudo deploy/scripts/validate.sh --url https://books.example.com` |
| What is the worker doing? | `sudo deploy/scripts/status.sh` (`--json` for scripts) |
| Collect diagnostics | `sudo deploy/scripts/diagnose.sh > diagnose.txt` |
| Follow the logs | `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env logs -f app worker` |
| Back up now | `sudo deploy/scripts/backup.sh` |
| Restore a backup | `sudo deploy/scripts/restore.sh /srv/book-studio/backups/studio-….tar.gz` |
| Update | `sudo deploy/scripts/update.sh --pull` |
| Undo the last update | `sudo deploy/scripts/rollback.sh` |
| End-to-end check | `sudo deploy/validation/run_e2e.sh --url … --username … --password-file …` |
| New password for the account | `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env exec app python -m pbs_core reset-password author` |

## 1. Monitoring background jobs

AI jobs, publishing builds and exports run in the `worker` container from a durable queue in the
database. `status.sh` prints, for both AI jobs and build/export tasks: how many are queued, running,
succeeded, failed or interrupted; how long the oldest queued one has waited; the worker's last
heartbeat; content counts; free disk; the privacy mode. `validate.sh` (through `python -m pbs_core
check`) warns when no worker has reported in for a minute or something has been queued for over 15
minutes. In the browser, **AI jobs** lists every job with its log; on a server, a banner appears when
the worker is not running.

A job or task left running by a crash is retried once when the worker starts, then marked
`interrupted` (it can be retried from the UI). Only one worker can run per data folder (an OS file
lock); a second one exits.

To check every five minutes from cron and get a mail on failure (with a mail transfer agent set up):

```cron
*/5 * * * * root cd /opt/book-studio && deploy/scripts/validate.sh >/dev/null 2>&1 || echo "Book Studio check failed" | mail -s "Book Studio" you@example.com
```

## 2. Database migrations

The schema is managed by Alembic migrations that ship with the image. `install.sh`, `update.sh` and
`restore.sh` run `python -m pbs_core migrate` (or migrate on start) **before** the worker starts.
Every migration first saves a consistent copy of the database in `data/db-backups/`. Migrations only
move forward. A newer version refuses to open a database it does not know about, so going back to an
older version always means going back to a backup taken before the update. `rollback.sh` does exactly
that.

## 3. Backups

`backup.sh` stops `app` and `worker` for the few seconds the copy takes. That way the database and files
match. It then writes `studio-<time>-<label>.tar.gz` in `/srv/book-studio/backups` (root-only, mode
600) and restarts the studio. It then **verifies** the archive with the current image (safe file names,
a readable database, `PRAGMA integrity_check`, schema and content counts) and writes
`.manifest.json` and `.sha256` next to it. `--keep N` removes all but the newest N backups.

The archive holds the whole data folder: every book, revision, original, asset, export, recording,
setting, account, session and queued job, plus the encrypted key file. It does **not** hold the master
key. Keep `/srv/book-studio/secrets/pbs_master_key` in a separate safe place: without it, stored
provider keys cannot be decrypted after a restore on a new server (books are unaffected).

Nightly, keeping two weeks:

```cron
30 2 * * * root cd /opt/book-studio && deploy/scripts/backup.sh --label nightly --keep 14 >> /var/log/book-studio-backup.log 2>&1
```

Copy the backups folder off the server too (another disk, another machine or offline storage): a
backup on the same disk does not survive the disk.

## 4. Restore (tested recovery procedure)

```sh
sudo ls -1t /srv/book-studio/backups/*.tar.gz | head
sudo deploy/scripts/restore.sh /srv/book-studio/backups/studio-20261123T163000Z-nightly.tar.gz
```

What it does, in order:
1. checks the `.sha256`, then verifies the archive with the current image;
2. refuses an archive from a newer version;
3. asks you to type `RESTORE`;
4. stops the studio;
5. **moves** the current data folder to `data.pre-restore-<time>`;
6. extracts the backup and sets ownership;
7. starts the studio, which migrates an older backup if needed;
8. validates.

If any step fails, it prints how to put the previous folder back. Once you are satisfied, remove
`data.pre-restore-*` yourself.

On a **new server**:
1. Install as usual.
2. Copy the master key to `/srv/book-studio/secrets/pbs_master_key` (owner 10001, mode 400), replacing
   the one install created.
3. Copy the backup into `/srv/book-studio/backups`.
4. Run `restore.sh`.

This procedure was run end to end on the Ubuntu test system. A book created after the backup was gone
after the restore, and everything recorded before it was identical: chapters, every revision hash,
assets and exported files (BUILD_STATE, Phase 10).

## 5. Updates and rollback

`update.sh [--pull]`:
1. Takes a verified backup labelled `pre-update-<old tag>`.
2. Records it in `backups/last-update.env`.
3. Builds `personal-book-studio:<new git revision>` **next to** the old image.
4. Stops the studio, migrates, then starts and validates.

If the build fails, nothing changes. If migration or validation fails, it tells you to run
`rollback.sh`.

`rollback.sh`:
1. Switches back to the previous image.
2. Restores the pre-update backup with `restore.sh`. The post-update data is moved aside, not deleted.

Work saved after the update is not in that backup. Afterwards, check out the matching code
(`git checkout <old tag>`) so the next update starts from the right place. Old images stay until you
remove them yourself (`docker image ls personal-book-studio`). Keep at least the previous one.

## 6. Logs and diagnostics

* Container logs rotate at 10 MB × 5 files per service (Compose `logging` options).
* Core also writes JSON logs to `data/logs/core.jsonl` (rotated daily, 14 kept).
* Both are redacted: no API keys, passwords, session tokens or manuscript text; IDs and lengths only.
* `diagnose.sh` collects versions, container state, health history, disk, status, checks, recent
  backups and the last 150 log lines of each service.

| Symptom | Look at |
|---|---|
| Browser shows "Request host is not allowed" | The name used is not `PBS_DOMAIN`; NPM forwards the original Host |
| 502 from NPM | `status.sh`; is `app` healthy and is NPM on `PBS_PROXY_NETWORK`? |
| Uploads fail at about 1 MB | The NPM Advanced lines (`client_max_body_size`) are missing |
| Jobs stay queued | Worker not healthy: `compose logs worker`; a second worker exits by design |
| `validate.sh`: trusted proxy subnet mismatch | The NPM network was recreated: run `install.sh` again |
| Wrong master key after a move | Core stops at start with "does not match": restore the original key file |

## 7. End-to-end validation

`deploy/validation/run_e2e.sh` checks a running deployment as a user would, over HTTPS:
1. sign-in checks (anonymous, wrong password, missing CSRF token);
2. importing a representative DOCX (three chapters, headings, lists, a table and an image);
3. chapter structure and the stored image;
4. a model connection test;
5. an AI-assisted revision of a selected paragraph, approved by the author;
6. a further author revision;
7. DOCX, EPUB and PDF export in the worker;
8. a restart, then a full container recreation;
9. a backup, a change made after it, and a restore;
10. after each step, a check that every chapter, revision hash, asset and exported file is identical.

It leaves a book named "Validation <date>" behind. Do not use the studio while it runs: its last step restores the backup it took a minute earlier, so anything saved in between is set aside in `data.pre-restore-*`.

It does **not** judge whether the exported files meet a store's requirements. The studio's preflight
findings are recorded as they are. Check KDP or other stores' requirements with their own previewers.
