import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from helpers import normalize_manufacturer

CLIENT_ID = os.environ.get("DIGIKEY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("DIGIKEY_CLIENT_SECRET")
MAX_PARALLEL_REQUESTS = 10

STATUS_MAP = {
    "active": "Active",
    "not for new designs": "NRND",
    "last time buy": "Obsolete",
    "obsolete": "Obsolete",
    "discontinued at digikey": None,  # unknown
}

MANUFACTURER_MAP = {
    # "normalized_name": [mfr_id, mfr_id, ...],
}


class DigiKey:
    ID = "digikey"
    NAME = "DigiKey"
    URL = "https://digikey.com"
    LOGO_FILENAME = "parts-provider-digikey.png"

    def __init__(self, db, logger):
        self._db = db
        self._logger = logger

    def fetch(self, parts):
        # Filter out the parts which need to be requested and abort if
        # there are no parts to be requested.
        filtered_parts = [p for p in parts if "results" not in p]
        if len(filtered_parts) == 0:
            return 0

        with requests.Session() as session:
            # Get/refresh token, abort on error.
            token = self._get_token(session)
            if not token:
                return 0
            session.headers.update(
                {
                    "X-DIGIKEY-Client-Id": CLIENT_ID,
                    "X-DIGIKEY-Locale-Site": "US",
                    "X-DIGIKEY-Locale-Language": "en",
                    "X-DIGIKEY-Locale-Currency": "USD",
                    "X-DIGIKEY-Customer-Id": "0",
                    "Authorization": f"Bearer {token}",
                }
            )

            # Refresh manufacturers.
            self._refresh_manufacturers(session)

            # Fetch parts with multiple threads in parallel.
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as ex:
                futures = {
                    ex.submit(self._get_part, session, p): p for p in filtered_parts
                }
                for future in as_completed(futures):
                    if part_to_cache := future.result():  # re-throws exception
                        self._db.add_parts_cache(self.ID, part_to_cache)
        return 0

    def _get_token(self, session):
        if not CLIENT_ID or not CLIENT_SECRET:
            return False

        # Get token from database.
        token = self._db.get_key_value("digikey_token")
        validity = self._db.get_key_value("digikey_token_validity") or 0
        if validity > time.time() + 30.0:
            return token

        # Request new token.
        self._logger.debug("Refreshing token...")
        response = session.post(
            "https://api.digikey.com/v1/oauth2/token",
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            timeout=10.0,
        ).json()
        token = response.get("access_token")
        if token:
            expires_in = response.get("expires_in") or 599
            self._logger.debug(f"Got new token, expires in {expires_in}s")
        else:
            expires_in = 3600  # On error, wait 1 hour
            self._logger.error(f"Failed to get new token: {response}")

        # Store in database, no matter if valid or not.
        self._db.set_key_value("digikey_token", token)
        self._db.set_key_value("digikey_token_validity", int(time.time() + expires_in))
        return token

    def _refresh_manufacturers(self, session):
        # Check timestamp of last update.
        ts = self._db.get_key_value("digikey_manufacturers_timestamp") or 0
        if ts > time.time() - 7 * 24 * 3600:
            return

        # Store current timestamp in database, no matter if successful or not.
        self._db.set_key_value("digikey_manufacturers_timestamp", int(time.time()))

        # Request new list.
        self._logger.debug("Refreshing manufacturers...")
        response = session.get(
            "https://api.digikey.com/products/v4/search/manufacturers",
            timeout=10.0,
        )
        if self._handle_rate_limit(response):
            return

        # Normalize manufacturer names.
        rows = []
        for item in response.json()["Manufacturers"]:
            name = item["Name"]
            normalized = normalize_manufacturer(name)
            rows.append((item["Id"], name, normalized))

        # Store manufacturers in database.
        self._db.set_digikey_manufacturers(rows)
        self._logger.debug(f"Stored {len(rows)} manufacturers in database")

    def _get_part(self, session, part):
        mpn = urllib.parse.quote(part["mpn"], safe="")
        mfr = normalize_manufacturer(part["manufacturer"])
        mfr_ids = MANUFACTURER_MAP.get(mfr)
        if mfr_ids is None:
            mfr_ids = self._db.get_digikey_manufacturer_ids(mfr)
        if len(mfr_ids) == 0:
            self._logger.debug(f"Manufacturer not found: {mfr}")
            return None  # Don't store in cache

        part["results"] = 0
        for mfr_id in mfr_ids:
            response = session.get(
                f"https://api.digikey.com/products/v4/search/{mpn}/productdetails",
                params={"manufacturerId": mfr_id},
                timeout=10.0,
            )
            if self._handle_rate_limit(response):
                return None  # Don't store in cache
            product = response.json().get("Product")
            if product:
                part["results"] = 1

                product_url = str(product.get("ProductUrl", ""))
                if len(product_url):
                    part["product_url"] = product_url
                    part["pricing_url"] = product_url

                photo_url = str(product.get("PhotoUrl", ""))
                if len(photo_url):
                    part["picture_url"] = photo_url

                end_of_life = product.get("EndOfLife", False)
                product_status = str(
                    product.get("ProductStatus", {}).get("Status", "")
                ).lower()
                if end_of_life:
                    part["status"] = "Obsolete"
                elif len(product_status):
                    value = STATUS_MAP.get(product_status)
                    if value is not None:
                        part["status"] = value
                    elif product_status not in STATUS_MAP:
                        self._logger.warning(
                            f"Unknown part lifecycle status: {product_status}"
                        )

                qty_available = product.get("QuantityAvailable")
                normally_stocking = product.get("NormallyStocking", False)
                discontinued = product.get("Discontinued", False)
                if type(qty_available) is int:
                    if qty_available > 1000:
                        part["availability"] = 10
                    elif qty_available > 20:
                        part["availability"] = 5
                    elif qty_available > 0:
                        part["availability"] = 0
                    elif normally_stocking and not discontinued:
                        part["availability"] = -5
                    else:
                        part["availability"] = -10

                # Sort variations to avoid picking a variation with very high
                # BreakQuantity. Prefer variants with lower BreakQuantity.
                variations = product.get("ProductVariations", [])
                variations_prices = sorted(
                    [
                        prices
                        for v in variations
                        if (prices := self._get_prices_of_product_variation(v))
                    ],
                    key=lambda p: p[0]["quantity"],
                )
                if len(variations_prices):
                    part["prices"] = variations_prices[0]

                datasheet_url = str(product.get("DatasheetUrl", ""))
                if len(datasheet_url):
                    part["resources"] = [
                        {
                            "name": "Datasheet",
                            "mediatype": "application/pdf",
                            "url": datasheet_url,
                        },
                    ]
                return part  # Store in cache

        self._logger.debug(f"Part not found: '{mpn}' from '{mfr}'")
        return part  # Store in cache

    def _get_prices_of_product_variation(self, variation):
        prices = []
        for item in variation.get("StandardPricing", []):
            quantity = item.get("BreakQuantity")
            price = item.get("UnitPrice")
            if type(quantity) is int and type(price) in [float, int]:
                prices.append({"quantity": quantity, "price": price})
        return sorted(prices, key=lambda item: item["quantity"])

    def _handle_rate_limit(self, response):
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 3600))
            self._logger.error(f"Rate limit exceeded, retry after {retry_after}s")
            self._db.set_key_value("digikey_token", None)
            self._db.set_key_value(
                "digikey_token_validity", int(time.time() + retry_after)
            )
            return True
