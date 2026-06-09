# Link Shortener — FAS @ UniTN

University project for *Fondamenti di Amministrazione di Sistema*, University of Trento.

A self-hosted link shortener with a full observability stack: structured logs, Prometheus metrics, Grafana dashboards, and Sentry error tracking.

## Architecture

| Service | Image | Port |
|---|---|---|
| Flask app | local build | 5001 |
| MySQL 8 | `mysql:8` | — |
| Prometheus | `prom/prometheus` | 5003 |
| Grafana | `grafana/grafana` | 5002 |
| Loki | `grafana/loki` | — |

All services share a single Docker bridge network. Flask (5001) and Grafana (5002) are exposed on the host.

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/shorten` | Create a short link (`{"url": "https://..."}`) |
| `GET` | `/<code>` | Redirect to original URL |
| `GET` | `/stats/<code>` | JSON: clicks, creation date, expiry |
| `GET` | `/health` | Health check (DB connectivity) |
| `GET` | `/metrics` | Prometheus metrics |

## Quick start (local)

**Prerequisites:** Docker, Docker Compose v2

```bash
git clone git@github.com:StefanoVidesott/link_shortner-fas.git
cd link_shortner-fas

cp .env.example .env
# Edit .env — change passwords and set BASE_URL to your machine's IP/hostname.

mkdir -p data/mysql

docker compose up -d
```

After startup:
- App: http://localhost:5001
- Grafana: http://localhost:5002 (admin / `GRAFANA_ADMIN_PASSWORD` from `.env`)

## Production deployment (Ansible)

**Prerequisites (control node):**
```bash
ansible-galaxy collection install community.general ansible.posix
```

**Setup:**
```bash
cd ansible
cp vars.yml.example vars.yml
# Edit vars.yml — paste your SSH public key for the deploy user.
# Edit inventory.ini — set the server IP and admin username.

ansible-playbook -i inventory.ini playbook.yml --ask-become-pass
```

On first run the playbook creates `.env` on the server and stops — SSH in, edit the file, then re-run to bring the stack up.

## Observability

**Metrics (Prometheus + Grafana)**

The Flask app exposes these metrics at `/metrics`:

| Metric | Type | Labels |
|---|---|---|
| `http_requests_total` | Counter | `method`, `endpoint`, `http_status` |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` |
| `links_created_total` | Counter | — |
| `links_redirected_total` | Counter | — |
| `last_cleanup_success_timestamp_seconds` | Gauge | — |

A pre-built Grafana dashboard is provisioned automatically (folder: *Link Shortener*) with request rate, P50/P95/P99 latency, link activity stats, 5xx error rate, and cleanup heartbeat.

**Logs (Loki → Grafana)**

All Flask logs are structured JSON, ingested into Loki and queryable in Grafana. The `{level="ERROR"}` label is available for cheap filtering.

**Error tracking (Sentry)**

Set `SENTRY_DSN` in `.env` to enable. Leave blank to disable silently.

## Environment variables

See `.env.example` for the full list with descriptions.
