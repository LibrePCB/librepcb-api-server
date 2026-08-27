# -*- coding: utf-8 -*-

import fcntl


class CriticalSection:
    def __init__(self, path):
        self.path = path
        self._fh = None

    def __enter__(self):
        self._fh = open(self.path, "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()


MANUFACTURER_REPLACEMENTS = {
    ',': '',
    'ä': 'ae',
    'ö': 'oe',
    'ü': 'ue',
    'texas instruments': 'ti',
    'stmicroelectronics': 'st',
    'creeled': 'cree led',
}

MANUFACTURER_REMOVALS = set([
    'america',
    'contact',
    'devices',
    'electronics',
    'inc.',
    'inc',
    'incorporated',
    'industries',
    'integrated',
    'international',
    'limited',
    'ltd.',
    'ltd',
    'llc',
    'gmbh',
    'ag',
    'microelectronics',
    'semiconductor',
    'semiconductors',
    'solutions',
    'systems',
    'technology',
    'usa',
])

def normalize_manufacturer(name: str) -> str:
    name = name.lower()
    for old, new in MANUFACTURER_REPLACEMENTS.items():
        name = name.replace(old, new)
    terms = [s for s in name.split(' ') if s not in MANUFACTURER_REMOVALS]
    return ' '.join(terms)
