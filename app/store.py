"""데이터 저장소. MONGODB_URI가 있으면 MongoDB, 없으면 메모리(재시작 시 초기화)."""
import os
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc)


class MemoryStore:
    kind = "memory"

    def __init__(self):
        self.festivals, self.scans, self.responses = {}, [], []

    def upsert_festival(self, fest):
        self.festivals[fest["id"]] = fest

    def get_festival(self, fid):
        return self.festivals.get(fid)

    def list_festivals(self):
        return list(self.festivals.values())

    def add_scan(self, doc):
        self.scans.append(doc)

    def add_response(self, doc):
        self.responses.append(doc)

    def scans_for(self, fid, edition=None):
        return [s for s in self.scans if s["festival"] == fid and (edition is None or s["edition"] == edition)]

    def responses_for(self, fid, edition=None):
        return [r for r in self.responses if r["festival"] == fid and (edition is None or r["edition"] == edition)]

    def clear_festival(self, fid):
        self.scans = [s for s in self.scans if s["festival"] != fid]
        self.responses = [r for r in self.responses if r["festival"] != fid]


class MongoStore:
    kind = "mongodb"

    def __init__(self, uri):
        from pymongo import MongoClient

        self.db = MongoClient(uri, serverSelectionTimeoutMS=5000)["solunet"]
        self.db.scans.create_index([("festival", 1), ("edition", 1)])

    def upsert_festival(self, fest):
        self.db.festivals.replace_one({"id": fest["id"]}, fest, upsert=True)

    def get_festival(self, fid):
        return self.db.festivals.find_one({"id": fid}, {"_id": 0})

    def list_festivals(self):
        return list(self.db.festivals.find({}, {"_id": 0}))

    def add_scan(self, doc):
        self.db.scans.insert_one(dict(doc))

    def add_response(self, doc):
        self.db.responses.insert_one(dict(doc))

    def scans_for(self, fid, edition=None):
        q = {"festival": fid} | ({"edition": edition} if edition is not None else {})
        return list(self.db.scans.find(q, {"_id": 0}))

    def responses_for(self, fid, edition=None):
        q = {"festival": fid} | ({"edition": edition} if edition is not None else {})
        return list(self.db.responses.find(q, {"_id": 0}))

    def clear_festival(self, fid):
        self.db.scans.delete_many({"festival": fid})
        self.db.responses.delete_many({"festival": fid})


class PostgresStore:
    """Render 무료 PostgreSQL. 문서를 JSONB로 저장해서 Mongo와 같은 방식으로 쓴다."""
    kind = "postgres"

    def __init__(self, url):
        import psycopg
        from psycopg.types.json import Jsonb

        self.Jsonb, self.psycopg, self.url = Jsonb, psycopg, url
        self.conn = psycopg.connect(url, autocommit=True)
        with self.conn.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS festivals (id TEXT PRIMARY KEY, doc JSONB NOT NULL)")
            for t in ("scans", "responses"):
                c.execute(f"CREATE TABLE IF NOT EXISTS {t} (id BIGSERIAL PRIMARY KEY, festival TEXT NOT NULL, "
                          f"edition INT NOT NULL, doc JSONB NOT NULL)")
                c.execute(f"CREATE INDEX IF NOT EXISTS {t}_fe ON {t} (festival, edition)")

    def _q(self, sql, args=(), fetch=False, retry=True):
        try:
            with self.conn.cursor() as c:
                c.execute(sql, args)
                return c.fetchall() if fetch else None
        except self.psycopg.OperationalError:
            if not retry:
                raise
            self.conn = self.psycopg.connect(self.url, autocommit=True)  # 끊긴 연결 재접속
            return self._q(sql, args, fetch, retry=False)

    def upsert_festival(self, fest):
        self._q("INSERT INTO festivals (id, doc) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc",
                (fest["id"], self.Jsonb(fest)))

    def get_festival(self, fid):
        rows = self._q("SELECT doc FROM festivals WHERE id = %s", (fid,), fetch=True)
        return rows[0][0] if rows else None

    def list_festivals(self):
        return [r[0] for r in self._q("SELECT doc FROM festivals", fetch=True)]

    def _add(self, table, doc):
        self._q(f"INSERT INTO {table} (festival, edition, doc) VALUES (%s, %s, %s)",
                (doc["festival"], doc["edition"], self.Jsonb(doc)))

    def add_scan(self, doc):
        self._add("scans", doc)

    def add_response(self, doc):
        self._add("responses", doc)

    def _get(self, table, fid, edition):
        if edition is None:
            return [r[0] for r in self._q(f"SELECT doc FROM {table} WHERE festival = %s", (fid,), fetch=True)]
        return [r[0] for r in self._q(f"SELECT doc FROM {table} WHERE festival = %s AND edition = %s",
                                      (fid, edition), fetch=True)]

    def scans_for(self, fid, edition=None):
        return self._get("scans", fid, edition)

    def responses_for(self, fid, edition=None):
        return self._get("responses", fid, edition)

    def clear_festival(self, fid):
        self._q("DELETE FROM scans WHERE festival = %s", (fid,))
        self._q("DELETE FROM responses WHERE festival = %s", (fid,))


def make_store():
    if os.getenv("MONGODB_URI"):
        return MongoStore(os.getenv("MONGODB_URI"))
    if os.getenv("DATABASE_URL"):
        return PostgresStore(os.getenv("DATABASE_URL"))
    return MemoryStore()
