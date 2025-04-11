# -*- coding: utf-8 -*-

import json
import os

import requests
from flask import (Flask, g, make_response, request, send_from_directory,
                   url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

PARTS_MAX_COUNT = 10
PARTS_QUERY_TIMEOUT = 8.0
PARTS_QUERY_FRAGMENT = """
 fragment f on Stock {
  products {
   basic {
    manufacturer
    mfgpartno
    status
   }
   url
   imageUrl
   datasheetUrl
  }
  summary {
   inStockInventory
   medianPrice
   suppliersInStock
  }
 }
"""
PARTS_QUERY_STATUS_MAP = {
    'active': 'Active',
    'active-unconfirmed': 'Active',
    'nrfnd': 'NRND',
    'eol': 'Obsolete',
    'obsolete': 'Obsolete',
    'discontinued': 'Obsolete',
    'transferred': 'Obsolete',
    'contact mfr': None,  # Not supported, but here to avoid warning.
}
MANUFACTURER_REPLACEMENTS = {
    'ä': 'ae',
    'ö': 'oe',
    'ü': 'ue',
    'texas instruments': 'ti',
    'stmicroelectronics': 'st',
}
MANUFACTURER_REMOVALS = set([
    'contact',
    'devices',
    'electronics',
    'inc.',
    'inc',
    'incorporated',
    'integrated',
    'international',
    'limited',
    'ltd.',
    'ltd',
    'microelectronics',
    'semiconductor',
    'semiconductors',
    'solutions',
    'systems',
    'technology',
    'usa',
])


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


def _build_headers():
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json, multipart/mixed',
        'Authorization': 'Bearer {}'.format(_get_config('parts_query_token')),
    }


def _build_request(parts):
    args = []
    queries = []
    variables = {}
    for i in range(len(parts)):
        args.append('$mpn{}:String!'.format(i))
        queries.append('q{}:findStocks(mfgpartno:$mpn{}){{...f}}'.format(i, i))
        variables['mpn{}'.format(i)] = parts[i]['mpn']
    query = 'query Stocks({}) {{\n{}\n}}'.format(
        ','.join(args),
        '\n'.join(queries)
    ) + PARTS_QUERY_FRAGMENT
    return dict(query=query, variables=variables)


def _get_basic_value(product, key):
    if type(product) is dict:
        basic = product.get('basic')
        if type(basic) is dict:
            value = basic.get(key)
            if type(value) is str:
                return value
    return ''


def _normalize_manufacturer(mfr):
    mfr = mfr.lower()
    for old, new in MANUFACTURER_REPLACEMENTS.items():
        mfr = mfr.replace(old, new)
    terms = [s for s in mfr.split(' ') if s not in MANUFACTURER_REMOVALS]
    return ' '.join(terms)


def _calc_product_match_score(p, mpn_n, mfr_n):
    score = 0

    status_p = PARTS_QUERY_STATUS_MAP.get(_get_basic_value(p, 'status'))
    if status_p == 'Active':
        score += 200
    elif status_p == 'NRND':
        score += 100

    mpn_p = _get_basic_value(p, 'mfgpartno').lower()
    if mpn_p == mpn_n:
        score += 20  # MPN matches exactly.
    elif mpn_p.replace(' ', '') == mpn_n.replace(' ', ''):
        score += 10  # MPN matches when ignoring whitespaces.
    else:
        return 0  # MPN does not match!

    mfr_p = _normalize_manufacturer(_get_basic_value(p, 'manufacturer'))
    if mfr_p == mfr_n:
        score += 4  # Manufacturer matches exactly.
    elif mfr_n in mfr_p:
        score += 3  # Manufacturer matches partially.
    elif mfr_n.replace(' ', '') in mfr_p.replace(' ', ''):
        score += 2  # Manufacturer matches partially when ignoring whitespaces.
    elif mfr_n.split(' ')[0] in mfr_p:
        score += 1  # The first term of the manufacturer matches.
    else:
        return 0  # Manufacturer does not match!

    return score


def _get_product(data, mpn, manufacturer):
    products = (data.get('products') or [])
    for p in products:
        p['_score'] = _calc_product_match_score(
            p, mpn.lower(), _normalize_manufacturer(manufacturer))
    products = sorted([p for p in products if p['_score'] > 0],
                      key=lambda p: p['_score'], reverse=True)
    return products[0] if len(products) else None


def _add_pricing_url(out, data):
    value = data.get('url')
    if value is not None:
        out['pricing_url'] = value


def _add_image_url(out, data):
    value = data.get('imageUrl')
    if value is not None:
        out['picture_url'] = value


def _add_status(out, data):
    status = data.get('status') or ''
    status_n = status.lower()
    value = PARTS_QUERY_STATUS_MAP.get(status_n.lower())
    if value is not None:
        out['status'] = value
    elif len(status_n) and (status_n not in PARTS_QUERY_STATUS_MAP):
        app.logger.warning('Unknown part lifecycle status: {}'.format(status))


def _stock_to_availability(stock):
    if stock > 100000:
        return 10  # Very Good
    elif stock > 5000:
        return 5  # Good
    elif stock > 200:
        return 0  # Normal
    elif stock > 0:
        return -5  # Bad
    else:
        return -10  # Very Bad


def _suppliers_to_availability(suppliers):
    if suppliers > 30:
        return 10  # Very Good
    elif suppliers > 9:
        return 5  # Good
    elif suppliers > 1:
        return 0  # Normal
    elif suppliers > 0:
        return -5  # Bad
    else:
        return -10  # Very Bad


def _add_availability(out, data):
    stock = data.get('inStockInventory')
    suppliers = data.get('suppliersInStock')
    values = []
    if type(stock) is int:
        values.append(_stock_to_availability(stock))
    if type(suppliers) is int:
        values.append(_suppliers_to_availability(suppliers))
    if len(values):
        out['availability'] = min(values)


def _add_prices(out, summary):
    value = summary.get('medianPrice')
    if type(value) in [float, int]:
        out['prices'] = [dict(quantity=1, price=float(value))]


def _add_resources(out, data):
    value = data.get('datasheetUrl')
    if value is not None:
        out['resources'] = [
            dict(name="Datasheet", mediatype="application/pdf", url=value),
        ]


@app.route('/api/v1/parts', methods=['GET'])
def parts():
    enabled = _get_config('parts_operational', False)
    response = make_response(dict(
        provider_name='Partstack',
        provider_url='https://partstack.com',
        provider_logo_url=url_for('parts_static',
                                  filename='parts-provider-partstack.png',
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

    # Query parts from information provider.
    query_response = requests.post(
        _get_config('parts_query_url'),
        headers=_build_headers(),
        json=_build_request(parts),
        timeout=PARTS_QUERY_TIMEOUT,
    )
    query_json = query_response.json()
    data = query_json.get('data') or {}
    errors = query_json.get('errors') or []
    if (len(data) == 0) and (type(query_json.get('message')) is str):
        errors.append(query_json['message'])
    for error in errors:
        app.logger.warning("GraphQL Error: " + str(error))

    # Handle quota limit.
    next_access_time = query_json.get('nextAccessTime')
    if (len(data) == 0) and (next_access_time is not None):
        app.logger.warning("Quota limit: " + str(next_access_time))
        _write_status(dict(next_access_time=next_access_time))

    # Convert query response data and return it to the client.
    tx = dict(parts=[])
    for i in range(len(parts)):
        mpn = parts[i]['mpn']
        manufacturer = parts[i]['manufacturer']
        part_data = data.get('q' + str(i)) or {}
        product = _get_product(part_data, mpn, manufacturer)
        part = dict(
            mpn=mpn,
            manufacturer=manufacturer,
            results=0 if product is None else 1,
        )
        if product is not None:
            basic = product.get('basic') or {}
            summary = part_data.get('summary') or {}
            _add_pricing_url(part, product)
            _add_image_url(part, product)
            _add_status(part, basic)
            _add_availability(part, summary)
            _add_prices(part, summary)
            _add_resources(part, product)
        tx['parts'].append(part)
    return tx


@app.route('/api/v1/parts/static/<filename>', methods=['GET'])
def parts_static(filename):
    return send_from_directory(
        'static', filename, mimetype='image/png', max_age=24*3600)
