# -*- coding: utf-8 -*-

import requests

QUERY_FRAGMENT = """
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
QUERY_STATUS_MAP = {
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


class Partstack:
    ID = 'partstack'
    NAME = 'Partstack'
    URL = 'https://partstack.com'
    LOGO_FILENAME = 'parts-provider-partstack.png'

    def __init__(self, query_url, query_token, query_timeout, db, logger):
        self._query_url = query_url
        self._query_token = query_token
        self._query_timeout = query_timeout
        self._db = db
        self._logger = logger

    def fetch(self, parts, status):
        # Request parts data.
        query_response = requests.post(
            self._query_url,
            headers=self._build_headers(),
            json=self._build_request(parts),
            timeout=self._query_timeout,
        )
        query_json = query_response.json()
        data = query_json.get('data') or {}
        errors = query_json.get('errors') or []
        if (len(data) == 0) and (type(query_json.get('message')) is str):
            errors.append(query_json['message'])
        for error in errors:
            self._logger.warning("GraphQL Error: " + str(error))

        # Handle quota limit.
        next_access_time = query_json.get('nextAccessTime')
        if (len(data) == 0) and (next_access_time is not None):
            self._logger.warning("Quota limit: " + str(next_access_time))
            status['next_access_time'] = next_access_time

        # Convert query response data.
        for i in range(len(parts)):
            if 'results' not in parts[i]:
                mpn = parts[i]['mpn']
                manufacturer = parts[i]['manufacturer']
                part_data = data.get('q' + str(i)) or {}
                product = self._get_product(part_data, mpn, manufacturer)
                if product is not None:
                    parts[i]['results'] = 1
                    basic = product.get('basic') or {}
                    summary = part_data.get('summary') or {}
                    self._add_pricing_url(parts[i], product)
                    self._add_image_url(parts[i], product)
                    self._add_status(parts[i], basic)
                    self._add_availability(parts[i], summary)
                    self._add_prices(parts[i], summary)
                    self._add_resources(parts[i], product)
                self._db.add_parts_cache(self.ID, parts[i])
        return 0

    def _build_headers(self):
        return {
            'Content-Type': 'application/json',
            'Accept': 'application/json, multipart/mixed',
            'Authorization': 'Bearer {}'.format(self._query_token),
        }

    def _build_request(self, parts):
        args = []
        queries = []
        variables = {}
        for i in range(len(parts)):
            query = 'q{}:findStocks(mfgpartno:$mpn{}){{...f}}'.format(i, i)
            args.append('$mpn{}:String!'.format(i))
            queries.append(query)
            variables['mpn{}'.format(i)] = parts[i]['mpn']
        query = 'query Stocks({}) {{\n{}\n}}'.format(
            ','.join(args),
            '\n'.join(queries)
        ) + QUERY_FRAGMENT
        return dict(query=query, variables=variables)

    def _get_product(self, data, mpn, manufacturer):
        products = (data.get('products') or [])
        for p in products:
            p['_score'] = self._calc_product_match_score(
                p, mpn.lower(), self._normalize_manufacturer(manufacturer))
        products = sorted([p for p in products if p['_score'] > 0],
                          key=lambda p: p['_score'], reverse=True)
        return products[0] if len(products) else None

    def _calc_product_match_score(self, p, mpn_n, mfr_n):
        score = 0

        status_p = QUERY_STATUS_MAP.get(self._get_basic_value(p, 'status'))
        if status_p == 'Active':
            score += 200
        elif status_p == 'NRND':
            score += 100

        mpn_p = self._get_basic_value(p, 'mfgpartno').lower()
        if mpn_p == mpn_n:
            score += 20  # MPN matches exactly.
        elif mpn_p.replace(' ', '') == mpn_n.replace(' ', ''):
            score += 10  # MPN matches when ignoring whitespaces.
        else:
            return 0  # MPN does not match!

        mfr_p = self._normalize_manufacturer(
            self._get_basic_value(p, 'manufacturer'))
        if mfr_p == mfr_n:
            score += 4  # Manufacturer matches exactly.
        elif mfr_n in mfr_p:
            score += 3  # Manufacturer matches partially.
        elif mfr_n.replace(' ', '') in mfr_p.replace(' ', ''):
            score += 2  # Manufacturer matches partially when ignoring spaces.
        elif mfr_n.split(' ')[0] in mfr_p:
            score += 1  # The first term of the manufacturer matches.
        else:
            return 0  # Manufacturer does not match!

        return score

    def _get_basic_value(self, product, key):
        if type(product) is dict:
            basic = product.get('basic')
            if type(basic) is dict:
                value = basic.get(key)
                if type(value) is str:
                    return value
        return ''

    def _normalize_manufacturer(self, mfr):
        mfr = mfr.lower()
        for old, new in MANUFACTURER_REPLACEMENTS.items():
            mfr = mfr.replace(old, new)
        terms = [s for s in mfr.split(' ') if s not in MANUFACTURER_REMOVALS]
        return ' '.join(terms)

    def _add_pricing_url(self, out, data):
        value = data.get('url')
        if value is not None:
            out['pricing_url'] = value

    def _add_image_url(self, out, data):
        value = data.get('imageUrl')
        if value is not None:
            out['picture_url'] = value

    def _add_status(self, out, data):
        status = data.get('status') or ''
        status_n = status.lower()
        value = QUERY_STATUS_MAP.get(status_n.lower())
        if value is not None:
            out['status'] = value
        elif len(status_n) and (status_n not in QUERY_STATUS_MAP):
            self._logger.warning(f'Unknown part lifecycle status: {status}')

    def _add_availability(self, out, data):
        stock = data.get('inStockInventory')
        suppliers = data.get('suppliersInStock')
        values = []
        if type(stock) is int:
            values.append(self._stock_to_availability(stock))
        if type(suppliers) is int:
            values.append(self._suppliers_to_availability(suppliers))
        if len(values):
            out['availability'] = min(values)

    def _stock_to_availability(self, stock):
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

    def _suppliers_to_availability(self, suppliers):
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

    def _add_prices(self, out, summary):
        value = summary.get('medianPrice')
        if type(value) in [float, int]:
            out['prices'] = [dict(quantity=1, price=float(value))]

    def _add_resources(self, out, data):
        value = data.get('datasheetUrl')
        if value is not None:
            out['resources'] = [
                dict(name="Datasheet", mediatype="application/pdf", url=value),
            ]
