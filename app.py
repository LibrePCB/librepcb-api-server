# -*- coding: utf-8 -*-

import json
import os

from flask import (Flask, g, make_response, request, send_from_directory,
                   url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

from provider_partstack import Partstack

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

PARTS_MAX_COUNT = 10
PARTS_QUERY_TIMEOUT = 8.0


def _get_config(key, fallback=None):
    if 'config' not in g:
        try:
            with open('/config/api.json', 'rb') as f:
                g.config = json.load(f)
        except Exception as e:
            app.logger.critical(str(e))
            g.config = dict()
    return g.config.get(key, fallback)


def _write_status(key_values):
    status = dict()
    fp = '/config/status.json'
    if os.path.exists(fp):
        try:
            with open(fp, 'r') as f:
                status = json.load(f)
        except Exception as e:
            app.logger.critical(str(e))
    for key, value in key_values.items():
        status[key] = value
    try:
        with open(fp + '~', 'w') as f:
            f.write(json.dumps(status, indent=4))
        os.replace(fp + '~', fp)
    except Exception as e:
        app.logger.critical(str(e))


@app.route('/api/v1/parts', methods=['GET'])
def parts():
    enabled = _get_config('parts_operational', False)
    provider = Partstack
    response = make_response(dict(
        provider_name=provider.NAME,
        provider_url=provider.URL,
        provider_logo_url=url_for('parts_static',
                                  filename=provider.LOGO_FILENAME,
                                  _external=True),
        info_url='https://api.librepcb.org/api',
        query_url=url_for('parts_query', _external=True) if enabled else None,
        max_parts=PARTS_MAX_COUNT,
    ))
    response.headers['Cache-Control'] = 'max-age=300'
    return response


@app.route('/api/v1/parts/query', methods=['POST'])
def parts_query():
    # Get requested parts.
    payload = request.get_json()
    parts = payload['parts'][:PARTS_MAX_COUNT]
    parts = [dict(mpn=p['mpn'], manufacturer=p['manufacturer']) for p in parts]

    # Fetch parts from provider.
    status = dict()
    provider = Partstack(_get_config('parts_query_url'),
                         _get_config('parts_query_token'),
                         PARTS_QUERY_TIMEOUT, app.logger)
    provider.fetch(parts, status)

    # Handle status changes.
    if len(status):
        _write_status(status)

    # Complete parts which were not found.
    for part in parts:
        if 'results' not in part:
            part['results'] = 0

    # Return response.
    return dict(parts=parts)


@app.route('/api/v1/parts/static/<filename>', methods=['GET'])
def parts_static(filename):
    return send_from_directory(
        'static', filename, mimetype='image/png', max_age=24*3600)
