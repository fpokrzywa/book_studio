# Installing Personal Book Studio on an Ubuntu server, and moving it later

A step-by-step guide. Part 1 installs the studio. Part 2 moves it to another server. Every command
runs on the server unless it says otherwise.

What you end up with: the studio at `https://books.example.com` (your own name), behind Nginx Proxy
Manager. All books, revisions, files and settings live in `/srv/book-studio`.

> **Tested on:** Ubuntu 24.04.5 with Docker Engine 29.10 and Nginx Proxy Manager 2.17.1, running inside a
> container on the development machine. It has not yet been run on a physical or cloud server, so treat
> your first install as the real test (step 9 checks everything).

---

## Part 1: Install

### 1. What you need

- A server running **Ubuntu 22.04 or 24.04 LTS** with a sudo-capable user. Minimum 2 CPU cores, 4 GB
  of RAM and 20 GB of disk, plus room for your books. More RAM if you run AI models on it (a small model
  needs about 1 GB; useful writing models need 8 GB or more).
- **A name for the studio**, such as `books.example.com` or `books.home.lan`. It must point to the
  server: in your DNS provider, your router's DNS, or the `hosts` file of each device that uses it.
- **Nginx Proxy Manager (NPM)**: either already running on this server, or installed in step 4.

### 2. Install Docker Engine

These are Docker's official Ubuntu instructions (https://docs.docker.com/engine/install/ubuntu/):

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo docker version && sudo docker compose version
```

### 3. Get the code

```sh
sudo git clone https://github.com/fpokrzywa/book_studio.git /opt/book-studio
cd /opt/book-studio
sudo git checkout phase/09-11-web-production   # until PRs #1 to #9 are merged into main
```

Once the pull requests are merged, skip the `checkout` line: `main` will have everything.

### 4. Nginx Proxy Manager

**If you already run NPM in Docker on this server**, find its container name and its network:

```sh
sudo docker ps --format '{{.Names}}' | grep -i proxy
sudo docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' <npm-container>
```

Use that network name in step 5 (`--proxy-network <name>`), or connect NPM to a new `npm_proxy`
network after step 5: `sudo docker network connect npm_proxy <npm-container>`.

**If you do not run NPM yet**, create the shared network and start NPM:

```sh
sudo docker network create npm_proxy
sudo mkdir -p /opt/npm && cd /opt/npm
sudo tee compose.yaml > /dev/null <<'EOF'
services:
  npm:
    image: jc21/nginx-proxy-manager:2.17.1
    restart: unless-stopped
    ports: ["80:80", "443:443", "127.0.0.1:81:81"]
    volumes: ["./data:/data", "./letsencrypt:/etc/letsencrypt"]
    networks: [npm_proxy]
networks:
  npm_proxy:
    external: true
EOF
sudo docker compose up -d
cd /opt/book-studio
```

NPM's admin page listens only on the server itself (port 81). From your own computer, open a tunnel
with `ssh -L 8181:127.0.0.1:81 you@your-server`, then browse to http://localhost:8181. On first visit,
NPM asks you to create its admin user.

### 5. Install the studio

```sh
cd /opt/book-studio
sudo deploy/scripts/install.sh --domain books.example.com --proxy-network npm_proxy
```

Useful options:

| Option | Effect |
|---|---|
| `--ollama docker` | Also run a local AI model server (Ollama) in Docker |
| `--no-cloud` | Cloud AI can never be used, whatever is chosen in the app |
| `--data-root /path` | Store everything somewhere other than `/srv/book-studio` |
| `--publish 192.168.1.20:8765 --trusted-proxy 192.168.1.10` | Only if NPM runs on **another** machine (192.168.1.10 here): publish the studio on this server's LAN address for NPM to reach |

The first install takes several minutes because it builds the image. What it does:
- creates `deploy/.env` (your settings) and `/srv/book-studio/{data,backups,secrets,ollama}`;
- creates the **master key** `/srv/book-studio/secrets/pbs_master_key`, which encrypts AI provider keys;
- builds the image, sets up the database, starts the studio, and checks it.

It ends with "validation PASSED" and the next steps.

> **Back up the master key now.** Copy `/srv/book-studio/secrets/pbs_master_key` to a password manager
> or a USB stick. Without it, stored AI keys cannot be decrypted after a move; books are unaffected.

### 6. Add the proxy host in NPM

In NPM: **Hosts → Proxy Hosts → Add Proxy Host**.
- **Details tab:**
  - Domain Names: `books.example.com` (exactly the `--domain` you used).
  - Scheme `http`, Forward Hostname `book-studio-app`, Forward Port `8765`.
  - Turn on **Block Common Exploits**.
- **SSL tab:** request a Let's Encrypt certificate, or pick one you uploaded. Turn on **Force SSL** and
  **HTTP/2**.
- **Advanced tab:** paste these lines. They allow large uploads and long imports.

  ```nginx
  client_max_body_size 4200m;
  proxy_request_buffering off;
  proxy_read_timeout 900s;
  proxy_send_timeout 900s;
  ```

**Certificates**
- **Public name, reachable from the internet:** Let's Encrypt in NPM needs ports 80 and 443 forwarded
  to the server.
- **Private name, home or office network only:** use Let's Encrypt with a **DNS challenge** (no open
  ports), or your own certificate.
- **Away from home:** prefer a VPN (WireGuard or Tailscale) over opening ports.

### 7. Open the studio and create your account

Browse to `https://books.example.com`. The studio asks for a one-time setup code:

```sh
sudo cat /srv/book-studio/data/runtime/setup-code.txt
```

Choose a username and a password of at least 12 characters. This is the studio's only account.

### 8. Optional: an AI model

- **Ollama in Docker** (installed with `--ollama docker`): download a model once, then in the studio go to
  **AI settings → Add provider → Ollama**, address `http://ollama:11434`, then **Test connection** and
  **Find models**:

  ```sh
  sudo docker run --rm -v /srv/book-studio/ollama:/root/.ollama --entrypoint sh ollama/ollama \
    -c 'ollama serve >/dev/null 2>&1 & sleep 5 && ollama pull llama3.2'
  ```

  Replace `llama3.2` with the model you want. Only `qwen2.5:0.5b` was tested here.
- **Ollama on another computer you trust:** add its address to `PBS_LOCAL_AI_HOSTS` in `deploy/.env`, for
  example `["ollama","host.docker.internal","192.168.1.50"]`, run `sudo deploy/scripts/update.sh`, then
  use `http://192.168.1.50:11434`.
- **Cloud (OpenAI, Anthropic, Gemini, Groq, xAI):** add the provider and its key in AI settings, then
  allow cloud AI. Each book also asks for your consent the first time.

### 9. Check everything

```sh
sudo deploy/scripts/validate.sh --url https://books.example.com
```

Every line should say PASS. For the full end-to-end test (import, AI edit, exports, restart, backup and
restore), see `docs/DEPLOYMENT_VERIFICATION.md` §3. Run it when nobody is using the studio.

### 10. Nightly backups

Add the cron job:

```sh
echo '30 2 * * * root cd /opt/book-studio && deploy/scripts/backup.sh --label nightly --keep 14 >> /var/log/book-studio-backup.log 2>&1' \
  | sudo tee /etc/cron.d/book-studio-backup
```

Backups land in `/srv/book-studio/backups`. Copy that folder to another disk or machine regularly; a
backup on the same disk does not survive the disk.

### Everyday commands

Run these from `/opt/book-studio`:

| Task | Command |
|---|---|
| Health check | `sudo deploy/scripts/validate.sh` |
| What the background worker is doing | `sudo deploy/scripts/status.sh` |
| Stop / start | `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env stop` / `... up -d` |
| Logs | `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env logs -f app worker` |
| Update to newer code | `sudo deploy/scripts/update.sh --pull` (backs up first) |
| Undo the last update | `sudo deploy/scripts/rollback.sh` |
| Back up / restore | `sudo deploy/scripts/backup.sh` / `sudo deploy/scripts/restore.sh <archive>` |
| Forgotten password | `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env exec app python -m pbs_core reset-password <username>` |
| Collect diagnostics | `sudo deploy/scripts/diagnose.sh > diagnose.txt` |

Never run `docker volume rm` or `rm -rf /srv/book-studio`. Those are the only things that delete your
books; none of the scripts do either.

---

## Part 2: Move to another server

The studio moves as a single backup file plus the master key. The old server keeps running untouched
until you are happy with the new one.

### 1. On the OLD server: back up

```sh
cd /opt/book-studio
sudo deploy/scripts/backup.sh --label move
sudo ls -1t /srv/book-studio/backups/studio-*-move.tar.gz | head -1   # note this file name
git rev-parse --short HEAD                                            # note the code version
```

The backup stops the studio for a few seconds, then verifies the archive.

### 2. Copy three things to the NEW server

Run this on the old server, as your normal user (it uses your SSH login to the new server):

```sh
B=$(sudo ls -1t /srv/book-studio/backups/studio-*-move.tar.gz | head -1)
mkdir -p ~/pbs-move && chmod 700 ~/pbs-move
sudo cp "$B" "$B.sha256" /srv/book-studio/secrets/pbs_master_key ~/pbs-move/
sudo chown -R "$USER" ~/pbs-move
scp ~/pbs-move/* you@new-server:/tmp/
shred -u ~/pbs-move/pbs_master_key            # do not leave a copy of the key lying around
```

| File | Why |
|---|---|
| `studio-…-move.tar.gz` (+ `.sha256`) | Every book, revision, original, image, export, recording, setting and the account |
| `pbs_master_key` | Decrypts the stored AI keys. Treat it like a password; step 4 deletes the `/tmp` copy |
| *(optional)* `/opt/book-studio/deploy/.env` | Your settings, to copy values from. Do not copy it over the new one blindly |
| *(optional)* `/srv/book-studio/ollama` | Downloaded models (or download them again on the new server) |

### 3. On the NEW server: install

Do Part 1 steps 1 to 5 on the new server, with the **same or a newer** code version (step 3 of Part 1).
Use the **same domain** if the name will move to this server. Use a new one if it changes.

### 4. On the NEW server: put the old key in place and restore

```sh
cd /opt/book-studio
sudo docker compose -f deploy/compose.yaml --env-file deploy/.env stop app worker
sudo install -m 400 -o 10001 -g 10001 /tmp/pbs_master_key /srv/book-studio/secrets/pbs_master_key
sudo mv /tmp/studio-*-move.tar.gz* /srv/book-studio/backups/
sudo deploy/scripts/restore.sh /srv/book-studio/backups/studio-*-move.tar.gz
sudo shred -u /tmp/pbs_master_key 2>/dev/null || true
```

Restore does the following:
- checks the archive;
- asks you to type `RESTORE`;
- moves the empty install's data aside;
- unpacks your studio;
- starts it, upgrading the database if the new code is newer;
- validates.

### 5. Point the name at the new server

1. Add the proxy host on the new server's NPM (Part 1, step 6).
2. Change your DNS (or `hosts` files) so the name points to the new server.
3. Check it: `sudo deploy/scripts/validate.sh --url https://books.example.com`.
4. Sign in with your existing username and password. Sessions from the old server end, so you sign in
   once more.

**If the domain changes:**
1. Set `PBS_DOMAIN=new.example.com` in `/opt/book-studio/deploy/.env`.
2. Run `sudo deploy/scripts/update.sh`.
3. Add the NPM proxy host for the new name.

The studio only answers to the name in `PBS_DOMAIN`.

### 6. Afterwards

- Open a few books and check their history and exports.
- Keep the old server stopped (not deleted) for a while:
  `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env stop`.
- Once you are sure, retire it, after copying its `/srv/book-studio/backups` somewhere safe.
- Set up the nightly backup cron job on the new server (Part 1, step 10).

### Moving data on the same server

For example, to a bigger disk:
1. Stop the studio.
2. Copy `/srv/book-studio` with `sudo rsync -aHX /srv/book-studio/ /mnt/bigdisk/book-studio/`.
3. Change `PBS_DATA_DIR`, `PBS_BACKUP_DIR`, `PBS_MASTER_KEY_FILE` and `PBS_OLLAMA_DIR` in `deploy/.env`.
4. Run `sudo deploy/scripts/update.sh`.
5. Keep the old folder until `validate.sh` passes.

---

More detail: `docs/DEPLOYMENT.md` (design and options), `docs/OPERATIONS.md` (backups, updates,
monitoring, troubleshooting), `docs/DEPLOYMENT_VERIFICATION.md` (what was tested),
`docs/USER_GUIDE.md` (using the studio).
