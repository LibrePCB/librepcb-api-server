# -*- coding: utf-8 -*-


class DummyProvider:
    ID = 'dummy'

    def __init__(self, db):
        self._db = db

    def fetch(self, parts, status):
        for i in range(len(parts)):
            part = parts[i]
            if 'results' not in part:
                self._fetch_part(part, i)
        return 0

    def _fetch_part(self, part, i):
        if i % 2:
            part['results'] = 1
            part['status'] = 'Active'
            part['prices'] = [dict(quantity=1, price=13.37)]
            self._db.add_parts_cache(self.ID, part)
