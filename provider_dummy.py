# -*- coding: utf-8 -*-


class DummyProvider:
    ID = 'dummy'

    def __init__(self):
        pass

    def fetch(self, parts, status):
        for i in range(len(parts)):
            part = parts[i]
            if 'results' not in part:
                self._fetch_part(part, i)

    def _fetch_part(self, part, i):
        if i % 2:
            part['results'] = 1
            part['status'] = 'Active'
            part['prices'] = [dict(quantity=1, price=13.37)]
