import sqlite3

from flask import Flask, g, make_response, request, send_from_directory, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from database import Database
from helpers import CriticalSection
from provider_cache import PartsCache
from provider_digikey import DigiKey

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

PARTS_MAX_COUNT = 10  # Rather low due to slow DigiKey API
PARTS_CACHE_MAX_AGE = 60 * 24 * 3600  # 60 days due to quota limits
LOCK_PATH = "/tmp/librepcb-api-server.lock"


def _get_db():
    db = getattr(g, "_db", None)
    if db is None:
        db = g._database = sqlite3.connect("/data/db.sqlite")
    return db


@app.teardown_appcontext
def _close_db(exception):
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


@app.route("/api/v1/parts", methods=["GET"])
def parts():
    provider = DigiKey
    response = make_response(
        {
            "provider_name": provider.NAME,
            "provider_url": provider.URL,
            "provider_logo_url": url_for(
                "parts_static", filename=provider.LOGO_FILENAME, _external=True
            ),
            "info_url": "https://api.librepcb.org/api",
            "query_url": url_for("parts_query", _external=True),
            "max_parts": PARTS_MAX_COUNT,
        }
    )
    response.headers["Cache-Control"] = "max-age=300"
    return response


@app.route("/api/v1/parts/query", methods=["POST"])
def parts_query():
    # Get requested parts.
    payload = request.get_json()
    parts = payload["parts"][:PARTS_MAX_COUNT]
    parts = [{"mpn": p["mpn"], "manufacturer": p["manufacturer"]} for p in parts]

    # Prepare database & providers.
    db = Database(_get_db(), app.logger)
    providers = [
        PartsCache(db, max_age=PARTS_CACHE_MAX_AGE),
        DigiKey(db, app.logger),
    ]

    # Fetch parts from providers. Must be done in a critical section to
    # avoid race conditions between reading and updating cache or tokens.
    cache_hits = 0
    with CriticalSection(LOCK_PATH):
        for provider in providers:
            cache_hits += provider.fetch(parts)

    # Complete parts which were not found.
    found = 0
    for part in parts:
        if "results" not in part:
            part["results"] = 0
        if part["results"] > 0:
            found += 1

    # Store request in database.
    app.logger.debug(
        f"Queried {len(parts)} parts, {cache_hits} from cache: "
        f"{found} found, {len(parts) - found} not found"
    )
    db.add_parts_request(len(parts), cache_hits, found)

    # Return response.
    return {"parts": parts}


@app.route("/api/v1/parts/static/<filename>", methods=["GET"])
def parts_static(filename):
    return send_from_directory(
        "static", filename, mimetype="image/png", max_age=24 * 3600
    )
