from ast import literal_eval


class Database:
    def __init__(self, db, logger):
        self._db = db
        self._logger = logger
        self._run_migrations()
        self._db.execute("VACUUM")  # Because of the auto cleanup

    def get_key_value(self, key: str):
        with self._db as db:
            cur = db.cursor()
            cur.execute(
                "SELECT integer, real, text, blob FROM key_values WHERE key=?", (key,)
            )
            row = cur.fetchone()
            for value in row or []:
                if value is not None:
                    return value
            return None

    def set_key_value(self, key: str, value):
        columns = {
            int: "integer",
            float: "real",
            str: "text",
            bytes: "blob",
            type(None): "integer",
        }
        column = columns[type(value)]
        with self._db as db:
            db.execute(
                f"INSERT INTO key_values (key, {column}) VALUES (?, ?) "
                f"ON CONFLICT(key) DO UPDATE "
                f"SET integer=excluded.integer, real=excluded.real, "
                f"    text=excluded.text, blob=excluded.blob",
                (key, value),
            )

    def add_parts_request(self, count: int, cache_hits: int, with_result: int):
        with self._db as db:
            db.execute(
                "INSERT INTO parts_requests "
                "(count, cache_hits, with_result) "
                "VALUES (?, ?, ?)",
                (count, cache_hits, with_result),
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
                (part["mpn"], part["manufacturer"], provider, str(part)),
            )

    def get_parts_cache(self, mpn, manufacturer, max_age):
        with self._db as db:
            cur = db.cursor()
            cur.execute(
                "SELECT part FROM parts_cache "
                "WHERE mpn=? AND manufacturer=? "
                "AND datetime >= datetime('now', ?)"
                "ORDER BY datetime DESC",
                (mpn, manufacturer, f"-{max_age} seconds"),
            )
            row = cur.fetchone()
            return literal_eval(row[0]) if row is not None else None

    def set_digikey_manufacturers(self, rows):
        with self._db as db:
            db.execute("DELETE FROM digikey_manufacturers")
            db.executemany(
                "INSERT INTO digikey_manufacturers (id, name, normalized) "
                "VALUES (?, ?, ?)",
                rows,
            )

    def get_digikey_manufacturer_ids(self, normalized_name, limit=3):
        with self._db as db:
            cur = db.cursor()
            cur.execute(
                "SELECT id FROM digikey_manufacturers "
                "WHERE normalized=? OR normalized LIKE '%' || ? || '%' "
                "ORDER BY "
                "  CASE WHEN normalized=? THEN 0 ELSE 1 END, "
                "  length(normalized) "
                "LIMIT ?",
                (normalized_name, normalized_name, normalized_name, limit),
            )
            return [row[0] for row in cur.fetchall()]

    def _run_migrations(self):
        with self._db as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            while self._migrate_to(db, version + 1):
                version += 1

    def _migrate_to(self, db, version):
        if hasattr(self, f"_migrate_to_v{version}"):
            self._logger.info(f"Migrating database to version {version}...")
            getattr(self, f"_migrate_to_v{version}")(db)
            db.execute(f"PRAGMA user_version={version}")
            return True
        return False

    def _migrate_to_v1(self, db):
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

    def _migrate_to_v2(self, db):
        db.execute("""
            CREATE TABLE IF NOT EXISTS key_values (
                key TEXT PRIMARY KEY NOT NULL,
                integer INTEGER,
                real REAL,
                text TEXT,
                blob BLOB
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS digikey_manufacturers (
                id INTEGER NOT NULL,
                name TEXT NOT NULL,
                normalized TEXT NOT NULL
            )
        """)
