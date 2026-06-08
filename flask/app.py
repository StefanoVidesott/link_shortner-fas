import os
import json
import time
import string
import random
import secrets
import logging
import urllib.request
import urllib.error
import concurrent.futures
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

import mysql.connector
from flask import (
    Flask, request, jsonify, redirect, g,
    render_template, session, url_for, flash,
)
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger
from apscheduler.schedulers.background import BackgroundScheduler

# --- Sentry (optional, only when SENTRY_DSN is set) ---
_sentry_dsn = os.environ.get("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
    )

app = Flask(__name__)

# --- Structured JSON logging ---
_handler = logging.StreamHandler()
_handler.setFormatter(
    jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
)
_log = logging.getLogger("app")
_log.addHandler(_handler)
_log.setLevel(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# --- Prometheus metrics ---
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)
links_created_total    = Counter("links_created_total",    "Total links created")
links_redirected_total = Counter("links_redirected_total", "Total redirects")
last_cleanup_success_timestamp_seconds = Gauge(
    "last_cleanup_success_timestamp_seconds",
    "Unix timestamp of last successful cleanup run",
)

# --- Config ---
DB_CONFIG = {
    "host":     os.environ.get("MYSQL_HOST", "mysql"),
    "port":     int(os.environ.get("MYSQL_PORT", "3306")),
    "user":     os.environ.get("MYSQL_USER", "app"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "linkshortener"),
}
LINK_TTL_DAYS         = int(os.environ.get("LINK_TTL_DAYS", "30"))
BASE_URL              = os.environ.get("BASE_URL", "http://localhost:5000")
CLEANUP_INTERVAL_MINS = int(os.environ.get("CLEANUP_INTERVAL_MINUTES", "10"))
ADMIN_USERNAME        = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD        = os.environ.get("ADMIN_PASSWORD", "")
SENTRY_URL            = os.environ.get("SENTRY_URL", "")

app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)


# --- DB helpers ---
def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            short_code   VARCHAR(10)  UNIQUE NOT NULL,
            original_url TEXT         NOT NULL,
            clicks       INT          DEFAULT 0,
            created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP,
            expires_at   DATETIME,
            is_fake      BOOLEAN      DEFAULT FALSE
        )
    """)
    # Migration: add is_fake to tables created before this column existed
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'links' AND COLUMN_NAME = 'is_fake'
    """)
    if cur.fetchone()[0] == 0:
        cur.execute("ALTER TABLE links ADD COLUMN is_fake BOOLEAN DEFAULT FALSE")
    conn.commit()
    cur.close()
    conn.close()


# --- Short code generation ---
_CODE_CHARS = string.ascii_letters + string.digits


def _gen_code(length: int = 6) -> str:
    return "".join(random.choices(_CODE_CHARS, k=length))


# --- Admin auth ---
def _admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# --- Observability URLs helper ---
def _obs_urls():
    parsed = urlparse(BASE_URL)
    host = f"{parsed.scheme}://{parsed.hostname}"
    return {
        "grafana":    f"{host}:3000",
        "prometheus": f"{host}:9090",
        "sentry":     SENTRY_URL or ("https://sentry.io" if _sentry_dsn else None),
    }


# --- Request hooks: auto-instrument all routes ---
@app.before_request
def _before():
    g.t0 = time.perf_counter()


@app.after_request
def _after(response):
    duration = time.perf_counter() - getattr(g, "t0", time.perf_counter())
    endpoint = request.endpoint or "unknown"
    http_requests_total.labels(
        method=request.method,
        endpoint=endpoint,
        http_status=response.status_code,
    ).inc()
    http_request_duration_seconds.labels(
        method=request.method,
        endpoint=endpoint,
    ).observe(duration)
    _log.info(
        "request",
        extra={
            "method":      request.method,
            "path":        request.path,
            "status_code": response.status_code,
            "duration_ms": round(duration * 1000, 2),
        },
    )
    return response


# ── Public routes ─────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/shorten", methods=["POST"])
def shorten():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or request.form.get("url", "")).strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    is_fake = bool(body.get("is_fake", False))

    code = _gen_code()
    expires_at = datetime.utcnow() + timedelta(days=LINK_TTL_DAYS)
    db = get_db()
    cur = db.cursor()
    for _ in range(5):
        try:
            cur.execute(
                "INSERT INTO links (short_code, original_url, expires_at, is_fake) "
                "VALUES (%s, %s, %s, %s)",
                (code, url, expires_at, is_fake),
            )
            db.commit()
            break
        except mysql.connector.IntegrityError:
            code = _gen_code()
    else:
        cur.close()
        return jsonify({"error": "could not generate unique short code"}), 500
    cur.close()

    links_created_total.inc()
    _log.info("link_created", extra={"short_code": code, "original_url": url, "is_fake": is_fake})
    return jsonify({"short_url": f"{BASE_URL}/{code}", "short_code": code}), 201


@app.route("/_error")
def trigger_error():
    raise RuntimeError("Simulated error triggered from admin panel")


@app.route("/<short_code>")
def redirect_link(short_code):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT original_url, expires_at FROM links WHERE short_code = %s", (short_code,)
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return jsonify({"error": "not found"}), 404
    if row["expires_at"] and row["expires_at"] < datetime.utcnow():
        return jsonify({"error": "link expired"}), 410

    cur2 = db.cursor()
    cur2.execute(
        "UPDATE links SET clicks = clicks + 1 WHERE short_code = %s", (short_code,)
    )
    db.commit()
    cur2.close()

    links_redirected_total.inc()
    _log.info("redirect", extra={"short_code": short_code, "url": row["original_url"]})
    return redirect(row["original_url"], code=302)


@app.route("/stats/<short_code>")
def stats(short_code):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT short_code, original_url, clicks, created_at, expires_at "
        "FROM links WHERE short_code = %s",
        (short_code,),
    )
    row = cur.fetchone()
    cur.close()

    if not row:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "short_code":   row["short_code"],
        "original_url": row["original_url"],
        "clicks":       row["clicks"],
        "created_at":   row["created_at"].isoformat() if row["created_at"] else None,
        "expires_at":   row["expires_at"].isoformat()  if row["expires_at"]  else None,
    })


@app.route("/health")
def health():
    db_ok = True
    try:
        cur = get_db().cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
    except Exception as exc:
        db_ok = False
        _log.error(
            "health_db_error",
            extra={"exc_type": type(exc).__name__, "error": str(exc)},
        )
    return jsonify({"status": "ok" if db_ok else "degraded", "db": "ok" if db_ok else "error"})


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


# ── Admin auth ────────────────────────────────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not ADMIN_PASSWORD:
            error = "Admin not configured — set ADMIN_PASSWORD in .env."
        elif (
            secrets.compare_digest(username, ADMIN_USERNAME)
            and secrets.compare_digest(password, ADMIN_PASSWORD)
        ):
            session["admin"] = True
            _log.info("admin_login", extra={"username": username})
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid credentials."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("home"))


# ── Admin dashboard ───────────────────────────────────────────────────────────

@app.route("/admin")
@_admin_required
def admin_dashboard():
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(
        "SELECT short_code, original_url, clicks, created_at, expires_at, is_fake "
        "FROM links ORDER BY created_at DESC"
    )
    links = cur.fetchall()
    cur.close()

    now = datetime.utcnow()
    total_clicks = sum(lnk["clicks"] for lnk in links)
    fake_count   = sum(1 for lnk in links if lnk["is_fake"])
    active_count = sum(
        1 for lnk in links
        if not lnk["expires_at"] or lnk["expires_at"] > now
    )

    return render_template(
        "admin.html",
        links=links,
        total=len(links),
        active=active_count,
        fake=fake_count,
        total_clicks=total_clicks,
        base_url=BASE_URL,
        urls=_obs_urls(),
    )


@app.route("/admin/links/<short_code>/delete", methods=["POST"])
@_admin_required
def admin_delete_link(short_code):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM links WHERE short_code = %s", (short_code,))
    db.commit()
    cur.close()
    _log.info("admin_link_deleted", extra={"short_code": short_code})
    flash(f"Link /{short_code} deleted.", "success")
    return redirect(url_for("admin_dashboard"))


# ── HTTP helpers for admin simulations ───────────────────────────────────────
# All simulations call back into localhost:5000 so every request goes through
# the full Flask pipeline (before/after hooks, metrics, logging, Sentry).
# Gunicorn --threads 4 ensures the process can handle concurrent self-calls.

_SELF = "http://127.0.0.1:5000"

# Opener that does NOT follow redirects (needed for /<code> which returns 302)
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_kw):
        return None

_opener = urllib.request.build_opener(_NoRedirect)


def _self_post(path, body):
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        f"{_SELF}{path}", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _self_get(path):
    try:
        _opener.open(f"{_SELF}{path}", timeout=5)
    except Exception:
        pass  # 302 raises HTTPError — that's fine, the route already ran


def _run_parallel(fn, args_list, workers=3):
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(fn, *a) for a in args_list]
        concurrent.futures.wait(futures, timeout=60)


# ── Admin actions ─────────────────────────────────────────────────────────────

_FAKE_URLS = [
    "https://example.com/test/{}",
    "https://en.wikipedia.org/wiki/Special:Random?ref={}",
    "https://httpbin.org/get?id={}",
    "https://www.example.org/demo/page/{}",
    "https://example.net/resource/{}",
]


@app.route("/admin/generate-fake", methods=["POST"])
@_admin_required
def admin_generate_fake():
    n = max(1, min(int(request.form.get("count", 10)), 100))
    payloads = [
        ("/shorten", {"url": random.choice(_FAKE_URLS).format(random.randint(1000, 9999)), "is_fake": True})
        for _ in range(n)
    ]
    _run_parallel(_self_post, payloads)
    flash(f"{n} fake link(s) generated via HTTP POST /shorten.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete-fake", methods=["POST"])
@_admin_required
def admin_delete_fake():
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM links WHERE is_fake = TRUE")
    deleted = cur.rowcount
    db.commit()
    cur.close()
    _log.info("fake_links_deleted", extra={"count": deleted})
    flash(f"{deleted} fake link(s) deleted.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/simulate-traffic", methods=["POST"])
@_admin_required
def admin_simulate_traffic():
    n = max(1, min(int(request.form.get("count", 20)), 500))
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT short_code FROM links WHERE expires_at IS NULL OR expires_at > NOW()")
    active = [row["short_code"] for row in cur.fetchall()]
    cur.close()

    if not active:
        flash("No active links to simulate traffic on.", "warning")
        return redirect(url_for("admin_dashboard"))

    targets = [("/" + random.choice(active),) for _ in range(n)]
    _run_parallel(_self_get, targets)
    flash(f"Simulated {n} HTTP GET visit(s) across {len(active)} link(s).", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/simulate-errors", methods=["POST"])
@_admin_required
def admin_simulate_errors():
    n = max(1, min(int(request.form.get("count", 3)), 20))
    _run_parallel(_self_get, [("/_error",)] * n)
    suffix = " and Sentry" if _sentry_dsn else ""
    flash(f"{n} HTTP error(s) triggered via GET /_error — check metrics{suffix}.", "success")
    return redirect(url_for("admin_dashboard"))


# ── Background cleanup worker ─────────────────────────────────────────────────

def _cleanup():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < NOW()"
        )
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        last_cleanup_success_timestamp_seconds.set(time.time())
        _log.info("cleanup_complete", extra={"deleted": deleted})
    except Exception as exc:
        _log.error(
            "cleanup_error",
            extra={"exc_type": type(exc).__name__, "error": str(exc)},
        )


# ── Startup ───────────────────────────────────────────────────────────────────

def _startup():
    for attempt in range(30):
        try:
            init_db()
            _log.info("db_initialized")
            break
        except Exception as exc:
            _log.warning(
                "db_init_retry",
                extra={"attempt": attempt + 1, "error": str(exc)},
            )
            time.sleep(2)
    else:
        _log.error("db_init_failed_giving_up")

    scheduler = BackgroundScheduler()
    scheduler.add_job(_cleanup, "interval", minutes=CLEANUP_INTERVAL_MINS)
    scheduler.start()
    _log.info("scheduler_started", extra={"interval_minutes": CLEANUP_INTERVAL_MINS})


_startup()
