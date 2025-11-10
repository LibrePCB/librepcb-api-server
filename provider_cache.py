# -*- coding: utf-8 -*-


class PartsCache:
    def __init__(self, db, max_age):
        self._db = db
        self._max_age = max_age

    def fetch(self, parts, status):
        hits = 0
        for part in parts:
            if 'results' not in part:
                if self._fetch_part(part):
                    hits += 1
        return hits

    def _fetch_part(self, part):
        result = self._db.get_parts_cache(part['mpn'], part['manufacturer'],
                                          self._max_age)
        if result is not None:
            part.update(result)
            return True
        else:
            return False
