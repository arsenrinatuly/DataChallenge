"""Хранилище на SQLite (один файл, без внешних зависимостей). Сложные поля — JSON."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  dataset TEXT,
  channel TEXT,
  language TEXT,
  audio_url TEXT,
  transcript TEXT NOT NULL,
  imported_at REAL
);
CREATE TABLE IF NOT EXISTS checklists (
  id TEXT PRIMARY KEY,
  name TEXT,
  version INTEGER,
  config TEXT NOT NULL,
  created_at REAL,
  is_default INTEGER DEFAULT 0,
  archived INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS evaluations (
  id TEXT PRIMARY KEY,
  conversation_id TEXT,
  checklist_id TEXT,
  checklist_snapshot TEXT,
  results TEXT,
  score TEXT,
  final_results TEXT,
  final_score TEXT,
  engine TEXT,
  meta TEXT,
  created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_eval_conv ON evaluations(conversation_id, created_at);
CREATE TABLE IF NOT EXISTS appeals (
  id TEXT PRIMARY KEY,
  evaluation_id TEXT,
  conversation_id TEXT,
  criterion_id TEXT,
  comment TEXT,
  author TEXT,
  status TEXT,
  decision TEXT,
  created_at REAL,
  decided_at REAL
);
"""


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with _lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ---------- helpers
    def _q(self, sql, args=()):
        with _lock:
            cur = self.db.execute(sql, args)
            rows = cur.fetchall()
            self.db.commit()
            return rows

    @staticmethod
    def _new_id(prefix):
        return f"{prefix}_{uuid.uuid4().hex[:10]}"

    # ---------- conversations
    def upsert_conversation(self, rec: dict, dataset: str):
        transcript = rec.get("transcript") or []
        if isinstance(transcript, str):
            transcript = json.loads(transcript)
        self._q(
            """INSERT INTO conversations(id,dataset,channel,language,audio_url,transcript,imported_at)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET dataset=excluded.dataset, channel=excluded.channel,
               language=excluded.language, audio_url=excluded.audio_url,
               transcript=excluded.transcript, imported_at=excluded.imported_at""",
            (str(rec["conversation_id"]), dataset, rec.get("channel"), rec.get("language"),
             rec.get("audio_url"), json.dumps(transcript, ensure_ascii=False), time.time()),
        )

    def _conv(self, r):
        return {"conversation_id": r["id"], "dataset": r["dataset"], "channel": r["channel"],
                "language": r["language"], "audio_url": r["audio_url"],
                "transcript": json.loads(r["transcript"])}

    def get_conversation(self, cid):
        rows = self._q("SELECT * FROM conversations WHERE id=?", (cid,))
        return self._conv(rows[0]) if rows else None

    def list_conversations(self, dataset=None):
        if dataset:
            rows = self._q("SELECT * FROM conversations WHERE dataset=? ORDER BY id", (dataset,))
        else:
            rows = self._q("SELECT * FROM conversations ORDER BY dataset, id")
        out = []
        for r in rows:
            c = self._conv(r)
            c["message_count"] = len(c.pop("transcript"))
            ev = self.latest_evaluation(r["id"])
            c["latest_evaluation"] = None if not ev else {
                "id": ev["id"], "checklist_id": ev["checklist_id"],
                "checklist_name": ev["checklist_snapshot"].get("name"),
                "checklist_version": ev["checklist_snapshot"].get("version"),
                "total": ev["final_score"]["total"],
                "original_total": ev["score"]["total"],
                "gross_error": ev["final_score"]["gross_error"],
                "engine": ev["engine"], "created_at": ev["created_at"],
                "open_appeals": self.count_appeals(ev["id"], "open"),
                "decided_appeals": self.count_appeals(ev["id"], "decided"),
            }
            out.append(c)
        return out

    def datasets(self):
        return [r["dataset"] for r in self._q("SELECT DISTINCT dataset FROM conversations ORDER BY dataset")]

    # ---------- checklists
    def _cl(self, r):
        cfg = json.loads(r["config"])
        cfg.update({"id": r["id"], "version": r["version"], "created_at": r["created_at"],
                    "is_default": bool(r["is_default"]), "archived": bool(r["archived"])})
        return cfg

    def save_checklist(self, cfg: dict, checklist_id: str | None = None, make_default=False):
        """Каждое сохранение — новая версия (старые оценки ссылаются на снимок)."""
        cfg = {k: v for k, v in cfg.items()
               if k not in ("id", "version", "created_at", "is_default", "archived")}
        family = checklist_id.split("@")[0] if checklist_id else self._new_id("cl")
        rows = self._q("SELECT MAX(version) v FROM checklists WHERE id LIKE ?", (family + "@%",))
        version = (rows[0]["v"] or 0) + 1
        new_id = f"{family}@{version}"
        with _lock:
            if make_default:
                self.db.execute("UPDATE checklists SET is_default=0")
            # прошлые версии этого семейства архивируем
            self.db.execute("UPDATE checklists SET archived=1 WHERE id LIKE ?", (family + "@%",))
            was_default = self.db.execute(
                "SELECT COUNT(*) FROM checklists WHERE id LIKE ? AND is_default=1",
                (family + "@%",)).fetchone()[0]
            if was_default:
                self.db.execute("UPDATE checklists SET is_default=0 WHERE id LIKE ?", (family + "@%",))
            self.db.execute(
                "INSERT INTO checklists(id,name,version,config,created_at,is_default,archived) VALUES(?,?,?,?,?,?,0)",
                (new_id, cfg.get("name"), version, json.dumps(cfg, ensure_ascii=False), time.time(),
                 1 if (make_default or was_default) else 0))
            self.db.commit()
        return self.get_checklist(new_id)

    def get_checklist(self, cid):
        rows = self._q("SELECT * FROM checklists WHERE id=?", (cid,))
        return self._cl(rows[0]) if rows else None

    def list_checklists(self, include_archived=False):
        sql = "SELECT * FROM checklists" + ("" if include_archived else " WHERE archived=0") + \
              " ORDER BY is_default DESC, created_at DESC"
        return [self._cl(r) for r in self._q(sql)]

    def default_checklist(self):
        rows = self._q("SELECT * FROM checklists WHERE is_default=1 AND archived=0 LIMIT 1")
        if rows:
            return self._cl(rows[0])
        lst = self.list_checklists()
        return lst[0] if lst else None

    def set_default(self, cid):
        with _lock:
            self.db.execute("UPDATE checklists SET is_default=0")
            self.db.execute("UPDATE checklists SET is_default=1 WHERE id=?", (cid,))
            self.db.commit()

    def archive_checklist(self, cid):
        self._q("UPDATE checklists SET archived=1, is_default=0 WHERE id=?", (cid,))

    # ---------- evaluations
    def _ev(self, r):
        return {"id": r["id"], "conversation_id": r["conversation_id"],
                "checklist_id": r["checklist_id"],
                "checklist_snapshot": json.loads(r["checklist_snapshot"]),
                "results": json.loads(r["results"]), "score": json.loads(r["score"]),
                "final_results": json.loads(r["final_results"]),
                "final_score": json.loads(r["final_score"]),
                "engine": r["engine"], "meta": json.loads(r["meta"] or "{}"),
                "created_at": r["created_at"]}

    def save_evaluation(self, ev: dict):
        ev.setdefault("id", self._new_id("ev"))
        ev.setdefault("created_at", time.time())
        self._q(
            """INSERT OR REPLACE INTO evaluations(id,conversation_id,checklist_id,checklist_snapshot,results,
               score,final_results,final_score,engine,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (ev["id"], ev["conversation_id"], ev["checklist_id"],
             json.dumps(ev["checklist_snapshot"], ensure_ascii=False),
             json.dumps(ev["results"], ensure_ascii=False), json.dumps(ev["score"], ensure_ascii=False),
             json.dumps(ev["final_results"], ensure_ascii=False),
             json.dumps(ev["final_score"], ensure_ascii=False), ev["engine"],
             json.dumps(ev.get("meta", {}), ensure_ascii=False), ev["created_at"]))
        return ev

    def get_evaluation(self, eid):
        rows = self._q("SELECT * FROM evaluations WHERE id=?", (eid,))
        return self._ev(rows[0]) if rows else None

    def latest_evaluation(self, conversation_id, checklist_id=None):
        if checklist_id:
            rows = self._q("SELECT * FROM evaluations WHERE conversation_id=? AND checklist_id=? "
                           "ORDER BY created_at DESC LIMIT 1", (conversation_id, checklist_id))
        else:
            rows = self._q("SELECT * FROM evaluations WHERE conversation_id=? ORDER BY created_at DESC LIMIT 1",
                           (conversation_id,))
        return self._ev(rows[0]) if rows else None

    def list_evaluations(self, conversation_id):
        rows = self._q("SELECT * FROM evaluations WHERE conversation_id=? ORDER BY created_at DESC",
                       (conversation_id,))
        return [self._ev(r) for r in rows]

    # ---------- appeals
    def _ap(self, r):
        return {"id": r["id"], "evaluation_id": r["evaluation_id"],
                "conversation_id": r["conversation_id"], "criterion_id": r["criterion_id"],
                "comment": r["comment"], "author": r["author"], "status": r["status"],
                "decision": json.loads(r["decision"]) if r["decision"] else None,
                "created_at": r["created_at"], "decided_at": r["decided_at"]}

    def create_appeal(self, evaluation_id, conversation_id, criterion_id, comment, author):
        aid = self._new_id("ap")
        self._q("INSERT INTO appeals(id,evaluation_id,conversation_id,criterion_id,comment,author,status,created_at)"
                " VALUES(?,?,?,?,?,?, 'open', ?)",
                (aid, evaluation_id, conversation_id, criterion_id, comment, author, time.time()))
        return self.get_appeal(aid)

    def get_appeal(self, aid):
        rows = self._q("SELECT * FROM appeals WHERE id=?", (aid,))
        return self._ap(rows[0]) if rows else None

    def list_appeals(self, status=None, evaluation_id=None):
        sql, args = "SELECT * FROM appeals WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if evaluation_id:
            sql += " AND evaluation_id=?"
            args.append(evaluation_id)
        sql += " ORDER BY created_at DESC"
        return [self._ap(r) for r in self._q(sql, args)]

    def count_appeals(self, evaluation_id, status):
        return self._q("SELECT COUNT(*) n FROM appeals WHERE evaluation_id=? AND status=?",
                       (evaluation_id, status))[0]["n"]

    def decide_appeal(self, aid, decision: dict):
        self._q("UPDATE appeals SET status='decided', decision=?, decided_at=? WHERE id=?",
                (json.dumps(decision, ensure_ascii=False), time.time(), aid))
        return self.get_appeal(aid)
