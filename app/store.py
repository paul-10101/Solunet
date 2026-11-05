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


def make_store():
    uri = os.getenv("MONGODB_URI")
    return MongoStore(uri) if uri else MemoryStore()
