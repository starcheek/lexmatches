# LexMatches

Language-learning reader: upload a PDF (or paste text), read it page by page with a
word/phrase-aligned interlinear translation under every line, listen to lines with local
text-to-speech, track how often you need the translation, export pages as standalone HTML.

Stack: React + Vite + shadcn (`src/`), Python 3.12 FastAPI (`backend/`), Postgres, MinIO.
Architecture, schema, API and data contracts: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run

```sh
cp .env.example .env        # optional; everything has local defaults
docker compose up -d --build
```

| Service | URL |
|---|---|
| Web app | http://localhost:3100 |
| API (direct) | http://localhost:8100/api/health, docs at http://localhost:8100/docs |
| Postgres | localhost:5544 (lexmatches / lexmatches) |
| MinIO S3 / console | http://localhost:9200 / http://localhost:9201 |

Without `ANTHROPIC_API_KEY` the API uses a deterministic **mock translator** (glossary +
`«word»` echoes) so the full pipeline works offline. Set the key (and optionally
`ANTHROPIC_MODEL`, default `claude-opus-5-5`) in `.env` and `docker compose up -d api` to use Claude.
Piper TTS voices (~63 MB per language) download in the background at startup into the `piper-voices`
volume (`PIPER_PRELOAD`, default: all configured languages); the reader shows "Preparing voice…" meanwhile.
Billing (Stripe) is off unless `STRIPE_SECRET_KEY` is set.

## Test round with remote testers

After a PC restart: start Docker Desktop, then run one command. It starts everything, opens a temporary
public HTTPS address (Cloudflare quick tunnel: no account, no open ports) and prints the links.

```sh
wsl -d Ubuntu -- sh /root/lexmatches/scripts/share.sh        # from Windows (PowerShell)
sh scripts/share.sh                                          # inside WSL, in the repo
sh scripts/share.sh new                                      # fresh public address
sh scripts/share.sh stop                                     # public address down, local site stays up
```

It prints the site address for testers, the private admin link and whether public sign-up is open.
The public address **changes every time the tunnel container starts** (PC restart, Docker restart, `new`):
run the script again and send testers the new one. It only works while this PC and Docker are running.

**Admin page** (`/admin#<ADMIN_TOKEN>`, link printed by the script):

- create a test account (password generated, "Copy login details" gives the text to send), reset a
  password, delete an account with all its data
- open / close public sign-up — keep it closed while the address is shared; every translated page is
  billed to your Anthropic key
- per account: books, translated pages, sessions, last seen, last IP
- "Problems": failed requests, server crashes with tracebacks, failed books/pages, error messages shown
  to users, rage clicks, slow requests, dead clicks

**Settings** live in `.env` (see `.env.example` for every option). The ones a test round depends on:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | real translation; empty = mock translator |
| `ADMIN_TOKEN` | opens the admin page and `/api/admin/*`; empty = admin is off |
| `JWT_SECRET` | signs logins; must not be the default from `.env.example` when the site is public |
| `API_PORT` | host port of the direct API (default 8100); set another when Windows has reserved 8100 |

After changing `.env`: `docker compose up -d api`. Public sign-up is not in `.env`; it is the switch on
the admin page (stored in the database).

**What is recorded** per browser session (`backend/app/routers/analytics.py`, `src/lib/track.ts`): IP,
account, browser, page views, clicks and shortcut keys, sampled mouse path, time and scroll depth per page,
and the problems listed above. Never recorded: text typed into fields, or book text. Raw data as JSON, with
`Authorization: Bearer <ADMIN_TOKEN>`: `/api/admin/analytics/sessions`, `/api/admin/analytics/sessions/<id>`,
`/api/admin/analytics/summary`, `/api/admin/problems`.

**If something does not start**

- `ports are not available ... 8100`: Windows reserved the port; put `API_PORT=8500` in `.env`.
- containers after a restart: `docker compose ps`; logs: `docker compose logs api` / `web` / `tunnel`.
- `sh e2e/run.sh` signs up new accounts, so it fails while public sign-up is closed; the admin spec needs
  `ADMIN_TOKEN=... sh e2e/run.sh admin`.

## Deploy on a server

Automatic deploy on every push to `master` (GitHub Actions), with the one-time server setup script:
[deploy/README.md](deploy/README.md). The manual steps below are the same thing by hand.

One Linux server, no GPU: 2 vCPU / 4 GB RAM / 50+ GB disk is the minimum (4 vCPU / 8 GB is comfortable),
Ubuntu 24.04, ports 22, 80 and 443 open. Not yet run on a real server: treat the first deploy as a test.

```sh
# on the server, as root
curl -fsSL https://get.docker.com | sh
git clone <this repo> /opt/lexmatches && cd /opt/lexmatches     # or copy the folder with scp/rsync
cp .env.example .env && nano .env                               # see below
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`.env` on the server — set all of these, with fresh random values (`openssl rand -hex 32`) for the secrets:

| Variable | Value |
|---|---|
| `SITE_DOMAIN` | the domain whose DNS A record points at the server, e.g. `read.example.com` |
| `JWT_SECRET`, `ADMIN_TOKEN` | random; never the values from `.env.example` or from your PC |
| `POSTGRES_PASSWORD`, `S3_SECRET_KEY` | random (set before the first start; changing them later needs a data migration) |
| `ANTHROPIC_API_KEY` | translation |
| `TTS_PROVIDER=xai`, `XAI_API_KEY`, `XAI_VOICE` | Grok voices; without the key the local Piper voice is used |

Small server (1 vCPU / 2 GB): also set `MAX_UPLOAD_MB=25`, keep `BOOK_WORKERS=1` (uploads are split one
at a time, the rest queue) and add swap: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap
/swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab`.

Caddy gets and renews the HTTPS certificate for `SITE_DOMAIN` by itself. The admin page is
`https://<domain>/admin#<ADMIN_TOKEN>`; close public sign-up there before sharing the address.
No domain yet: start without the prod file's Caddy by using the tunnel instead
(`docker compose --profile tunnel up -d` gives a temporary `trycloudflare.com` address, as on the PC).

Update: `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`.
Data lives in the Docker volumes `pgdata` (database) and `miniodata` (uploaded books, cached audio): back
these up, or enable the host's server backups.

## Test

```sh
docker compose run --rm api pytest                 # backend: auth, upload→pages, translation, TTS cache, ownership
docker compose run --rm -e RUN_PIPER_TESTS=1 api pytest tests/test_tts.py   # + real Piper synthesis (network)
sh e2e/run.sh                                      # Playwright (official image) against the running stack
```

`e2e/specs/reader.spec.ts`: paste a text → translate → glosses / tap-for-translation / paragraph translations /
help-click tracking → read aloud → 390 px layout → dark mode → progress → delete; upload
`tests/fixtures/fr_clean_prose.pdf` → processing → read aloud (word highlight, pause, speed, auto-advance to
page 2) → translate page 1 → next page prefetched; the logged-out demo. It uses the api's translator (with
Claude ~3 pages per run). `review.spec.ts` is a free screenshot tour of the other screens. Screenshots go to
`e2e/screenshots/` (`before/` = the UI before the reader redesign).
Rebuild the api image after changing backend tests (`docker compose build api`).

## Frontend development

```sh
docker compose up -d postgres minio api
npm install && npm run dev     # http://localhost:5173, /api proxied to localhost:8100
npm run typecheck && npm run lint && npm run build
```

## Fixtures

`tests/fixtures/*.pdf` are small French PDFs for extraction work (clean prose, two columns,
headings/lists/footnotes/running header+footer, hyphenated line breaks). Regenerate with
`docker compose run --rm -v "$PWD/tests/fixtures:/fixtures" api python /fixtures/generate.py`.
