# -*- coding: utf-8 -*-

from ast import literal_eval


class Database:
    def __init__(self, db, logger):
        self._db = db
        self._logger = logger

        with self._db as db:
            db_version = db.execute('PRAGMA user_version').fetchone()[0]
            if db_version < 1:
                logger.info("Migrating database to version 1...")
                db.execute("""
                    CREATE TABLE IF NOT EXISTS parts_requests (
                        id INTEGER PRIMARY KEY NOT NULL,
                        datetime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        count INTEGER NOT NULL,
                        cache_hits INTEGER NOT NULL,
                        with_result INTEGER NOT NULL
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS parts_cache (
                        id INTEGER PRIMARY KEY NOT NULL,
                        mpn TEXT NOT NULL,
                        manufacturer TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        datetime TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        part TEXT NOT NULL,
                        UNIQUE(mpn, manufacturer, provider)
                    )
                """)
                db.execute('PRAGMA user_version=1')
        self._db.execute("VACUUM")

    def add_parts_request(self, count: int, cache_hits: int,
                          with_result: int):
        with self._db as db:
            db.execute(
                "INSERT INTO parts_requests "
                "(count, cache_hits, with_result) "
                "VALUES (?, ?, ?)",
                (count, cache_hits, with_result)
            )

    def add_parts_cache(self, provider: str, part: dict):
        with self._db as db:
            db.execute(
                "INSERT INTO parts_cache "
                "(mpn, manufacturer, provider, part) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(mpn, manufacturer, provider) DO UPDATE SET "
                "  datetime = CURRENT_TIMESTAMP, "
                "  part = excluded.part",
                (part['mpn'], part['manufacturer'], provider, str(part))
            )

    def get_parts_cache(self, mpn, manufacturer, max_age):
        with self._db as db:
            cur = db.cursor()
            cur.execute(
                "SELECT part FROM parts_cache "
                "WHERE mpn=? AND manufacturer=? "
                "AND datetime >= datetime('now', ?)"
                "ORDER BY datetime DESC",
                (mpn, manufacturer, f"-{max_age} seconds")
            )
            row = cur.fetchone()
            return literal_eval(row[0]) if row is not None else None
