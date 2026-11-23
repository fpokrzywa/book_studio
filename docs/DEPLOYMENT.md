# Deploying Personal Book Studio on an Ubuntu server

Personal Book Studio is a self-hosted web application. One author runs it on their own Ubuntu server
behind **Nginx Proxy Manager** (NPM) and opens it in any modern browser over HTTPS. Day-to-day
operations (backups, updates, monitoring, recovery) are in `docs/OPERATIONS.md`; the design reasons
are in ADR-0010 and ADR-0011.

**What was verified (2026-11-23):** an Ubuntu 24.04.5 LTS system with Docker Engine 29.10.0 and Docker
Compose v5.8.0, running inside a privileged container on this development machine (not a physical or
cloud server). Behind Nginx Proxy Manager 2.17.1 with a certificate from a private test CA. The full
procedure below was run there, including the end-to-end validation (BUILD_STATE, Phase 10 evidence).
Let's Encrypt certificates and access from other devices were not exercised.

## 1. What runs

| Service | What it is | Reachable from |
|---|---|---|
| `app` | Core, `PBS_ROLE=web`: the API and the built web UI. The only HTTP service | Only Docker networks: NPM reaches it as `http://book-studio-app:8765` |
| `worker` | Core, `PBS_ROLE=worker`: AI jobs, publishing builds and exports | Nothing; it only connects out |
| `ollama` (optional) | Local models in Docker (`PBS_OLLAMA=docker`) | Only `app` and `worker`, on an internal network with no internet |
| Nginx Proxy Manager | Yours: TLS, certificates, the public ports | Browsers |

There is **no separate database, Redis or message broker**: the studio keeps books, settings and its
durable job queue in SQLite inside the data folder (ADR-0011 explains why that is enough). Nothing of
the studio's is published on the host; only NPM publishes ports.

## 2. Install

Needs: Ubuntu 22.04 or 24.04 LTS with Docker Engine and the Compose plugin
(https://docs.docker.com/engine/install/ubuntu/), `git`, `openssl` and `python3` (for the validation
script; Ubuntu includes it). About 1 GB for the image plus your books.

```sh
sudo git clone https://github.com/fpokrzywa/book_studio.git /opt/book-studio
cd /opt/book-studio
sudo deploy/scripts/install.sh --domain books.example.com
```

`install.sh` is safe to run again; it never overwrites `deploy/.env`, the master key or data. It:

1. creates `deploy/.env` from `deploy/.env.example` (mode 600, git-ignored);
2. creates `/srv/book-studio/{data,backups,secrets,ollama}` (data owned by the studio's user 10001,
   mode 700; backups and secrets root-only) and the 32-byte master key (mode 400);
3. creates the Docker network `npm_proxy` if it does not exist and trusts forwarded headers only from
   its subnet;
4. builds the image `personal-book-studio:<git revision>`, migrates the database, starts `app` and
   `worker`, waits for both to be healthy and runs `validate.sh`.

Options: `--data-root DIR`, `--proxy-network NAME` (use the network your NPM already has),
`--ollama docker`, `--no-cloud` (cloud AI can never be used), and for NPM on another machine
`--publish 192.168.1.20:8765 --trusted-proxy 192.168.1.10` (see §3.3).

## 3. Nginx Proxy Manager and HTTPS

### 3.1 NPM on the same server (recommended)

If you do not run NPM yet, a minimal Compose file for it (NPM's own documentation:
https://nginxproxymanager.com/setup/):

```yaml
services:
  npm:
    image: jc21/nginx-proxy-manager:2.17.1
    restart: unless-stopped
    ports: ["80:80", "443:443", "127.0.0.1:81:81"]   # admin UI only on the server itself
    volumes: ["./data:/data", "./letsencrypt:/etc/letsencrypt"]
    networks: [npm_proxy]
networks:
  npm_proxy:
    external: true
```

For an existing NPM container: `sudo docker network connect npm_proxy <npm-container>`.

Reach the admin UI through an SSH tunnel (`ssh -L 8181:127.0.0.1:81 you@server`, then
http://localhost:8181). NPM supports `INITIAL_ADMIN_EMAIL` / `INITIAL_ADMIN_PASSWORD` for its first
user; NPM writes that password to its own log, so remove the variables after the first start and
change the password in NPM.

### 3.2 The proxy host

In NPM: **Hosts → Proxy Hosts → Add Proxy Host**

| Field | Value |
|---|---|
| Domain Names | `books.example.com` (exactly `PBS_DOMAIN`) |
| Scheme / Forward Hostname / Port | `http` / `book-studio-app` / `8765` |
| Block Common Exploits | on |
| Websockets Support | not needed |
| SSL tab | a certificate for the name; **Force SSL** on; HTTP/2 on. HSTS is sent by the studio itself |
| Advanced tab | the four lines below |

```nginx
client_max_body_size 4200m;
proxy_request_buffering off;
proxy_read_timeout 900s;
proxy_send_timeout 900s;
```

These allow uploads up to the studio's own limits (200 MB files, 4 GB backups) and long imports.
Then check from the server: `sudo deploy/scripts/validate.sh --url https://books.example.com`.

The studio answers only to `https://PBS_DOMAIN`: any other name (or an IP address) gets
"Request host is not allowed".

### 3.3 NPM on another machine

Set `PBS_PUBLISH_HTTP=<this server's LAN address>:8765` and
`PBS_TRUSTED_PROXIES=["<NPM machine's address>"]` in `deploy/.env` (or use the install options above),
then `sudo deploy/scripts/update.sh`. The scripts add `deploy/compose.publish.yaml`, which publishes Core
on that one address. Use a firewall so only the NPM machine can reach that port: the traffic between
NPM and the studio is plain HTTP on your LAN. **Docker-published ports bypass `ufw` rules**, so prefer
binding to an address only the NPM machine can reach, or use `DOCKER-USER` iptables rules.

### 3.4 Certificates and private remote access

* **Public name, open to the internet:** NPM's Let's Encrypt (HTTP challenge) needs ports 80 and 443
  forwarded to NPM. Only do this if you want the studio reachable from anywhere; it still needs the
  account password, and NPM Access Lists can add a second gate.
* **Private name (recommended for a personal studio):** keep ports closed to the internet and use
  Let's Encrypt with a **DNS challenge** in NPM (no inbound ports needed), or your own CA (upload it in
  NPM as a Custom certificate and trust the CA on your devices).
* **Remote access without opening ports:** a VPN such as WireGuard or Tailscale to the server, then the
  private name above. This is how to use the studio away from home without exposing it.

Not tested here: Let's Encrypt (either challenge) and VPN access; the verified setup used a custom
certificate from a private CA.

## 4. First sign-in

Open `https://books.example.com`. The studio asks for its one account and a one-time setup code
(never written to the log):

```sh
sudo cat /srv/book-studio/data/runtime/setup-code.txt
```

Or create the account on the server: `sudo docker compose -f deploy/compose.yaml --env-file deploy/.env exec app python -m pbs_core create-user author`.

## 5. AI models

| Where the model runs | Address in AI settings | Setup |
|---|---|---|
| Ollama container (`PBS_OLLAMA=docker`) | `http://ollama:11434` | It has no internet; pull models with the one-off command below |
| Ollama installed on the server | `http://host.docker.internal:11434` | Make Ollama listen on the Docker bridge: `sudo systemctl edit ollama` → `Environment="OLLAMA_HOST=172.17.0.1:11434"` (not 0.0.0.0) |
| Ollama on another trusted computer | `http://192.168.1.50:11434` | Add its address to `PBS_LOCAL_AI_HOSTS` in `deploy/.env`, run `update.sh`. Traffic is unencrypted on your LAN: use it only on a network you trust, or over a VPN |
| Cloud providers (OpenAI, Anthropic, Gemini, Groq, xAI) | built in | Enter the API key in AI settings (stored encrypted with the master key); allow cloud AI and consent per book |

Pull a model for the Ollama container (needs internet once; replace the model name):

```sh
sudo docker run --rm -v /srv/book-studio/ollama:/root/.ollama --entrypoint sh ollama/ollama \
  -c 'ollama serve >/dev/null 2>&1 & sleep 5 && ollama pull qwen2.5:0.5b'
```

**Testing a connection:** AI settings → each provider → **Test connection**, then **Refresh models**.
**Controls for cloud processing:** the studio starts in local-only mode. Cloud use needs the author to
allow it in AI settings *and* consent per book; `PBS_ALLOW_CLOUD=false` (or `install.sh --no-cloud`)
turns cloud AI off for the whole server, whatever the app says. `PBS_LOCAL_AI_HOSTS` is the only list
of hosts treated as local; nothing in the browser can add to it.

Verified here: the Ollama container (0.40.17) with `qwen2.5:0.5b`, through the full validation. Not
verified: Ollama installed natively on the host, a real second computer, and cloud providers with real
keys (their adapters have offline contract tests only).

## 6. Where your data lives

Everything is in host folders, so `docker compose down` (even with `-v`), image rebuilds and container
recreation never touch it.

| What | Path on the server |
|---|---|
| Database: books, chapters, every revision, settings, accounts, sessions, AI jobs, background tasks, knowledge index, canon | `/srv/book-studio/data/studio.db` (SQLite, WAL) |
| Imported originals, knowledge-source files and interview recordings (byte for byte, content-addressed) | `/srv/book-studio/data/originals/sha256/` |
| Images and other assets | `/srv/book-studio/data/projects/<book>/assets/` |
| Publishing files (DOCX, EPUB, PDF, covers, packages) | `/srv/book-studio/data/projects/<book>/publish/` |
| Narration audio and audio exports | `/srv/book-studio/data/narration/<book>/` |
| Per-book backups made in the app | `/srv/book-studio/data/backups/` |
| Encrypted provider keys | `/srv/book-studio/data/runtime/secrets.enc.json` |
| Snapshots taken before each migration | `/srv/book-studio/data/db-backups/` |
| Logs (JSON, redacted) | `/srv/book-studio/data/logs/` and `docker compose logs` |
| Master key (not in the data folder) | `/srv/book-studio/secrets/pbs_master_key` |
| Whole-studio backups | `/srv/book-studio/backups/` |
| Ollama models | `/srv/book-studio/ollama/` |

## 7. Optional tools in the image

| Tool | Used for | In the image |
|---|---|---|
| Typst (Python package) | Print PDF | Yes |
| eSpeak NG | Local narration | With `PBS_WITH_ESPEAK=1` in `deploy/.env`, then `update.sh` |
| Piper, Whisper | Local narration / transcription | No; the studio reports them as not installed |
| EPUBCheck (Java) | Optional EPUB validation | No; preflight says validation is unavailable |

## 8. Development without Docker

`scripts/dev.ps1` or `scripts/dev.sh` start Core on 127.0.0.1 and the Vite dev server (README).
