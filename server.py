#!/usr/bin/env python3
"""CQA backend: REST API + раздача статики фронтенда. Только стандартная библиотека Python 3.10+.

Запуск:  python server.py            (порт 8000, см. README)
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv(os.path.join(ROOT, ".env"))

from backend import evaluator, llm, scoring  # noqa: E402
from backend.storage import Store  # noqa: E402
from backend.transcript import normalize  # noqa: E402

WEB_DIR = os.path.join(ROOT, os.environ.get("CQA_WEB_DIR", "web"))
DB_PATH = os.environ.get("CQA_DB", os.path.join(ROOT, "data", "cqa.sqlite3"))
SOURCE_URL = os.environ.get(
    "CQA_SOURCE_URL",
    "https://ec88f21f1accecf38e20095a9fe175.a5.environment.api.powerplatform.com:443/powerautomate/automations/"
    "direct/cu/11/workflows/b3d2a68006a24662be2b721454cb4e00/triggers/manual/paths/invoke"
    "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=5Sog2MThgCRTlk3HObv70LRmRk6u7IOwzlwMpe804qo",
)
CONCURRENCY = int(os.environ.get("CQA_CONCURRENCY", "4"))

store = Store(DB_PATH)
pool = ThreadPoolExecutor(max_workers=CONCURRENCY)
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def ensure_default_checklist():
    if not store.list_checklists(include_archived=True):
        with open(os.path.join(ROOT, "data", "checklist_default.json"), encoding="utf-8") as f:
            store.save_checklist(json.load(f), make_default=True)


ensure_default_checklist()


class ApiError(Exception):
    def __init__(self, status, payload):
        super().__init__(str(payload))
        self.status, self.payload = status, payload


def bad(msg, status=400):
    raise ApiError(status, {"error": msg})


# ------------------------------------------------------------------ import
def records_from_payload(payload) -> tuple[str, list]:
    if isinstance(payload, list):
        return "UPLOAD", payload
    if not isinstance(payload, dict):
        bad("Ожидался JSON-объект или массив записей")
    if payload.get("isSuccess") is False:
        bad(f"Источник вернул ошибку: {payload.get('error')}", 502)
    data = payload.get("data", payload)
    recs = data.get("records")
    if not isinstance(recs, list):
        bad("Не найден массив records")
    return str(data.get("dataset_group_id") or payload.get("dataset") or "UPLOAD"), recs


def import_records(dataset, records):
    n = 0
    for r in records:
        if not r.get("conversation_id"):
            continue
        if isinstance(r.get("transcript"), str):
            r["transcript"] = json.loads(r["transcript"])
        store.upsert_conversation(r, dataset)
        n += 1
    return n


def fetch_dataset(group_id):
    parts = urllib.parse.urlsplit(SOURCE_URL)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True) if k != "group_id"]
    q.append(("group_id", group_id))
    url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(q)))
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}),
                                    timeout=120) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        bad(f"API организаторов: HTTP {e.code} {e.read()[:300]!r}", 502)
    except urllib.error.URLError as e:
        bad(f"API организаторов недоступен: {e.reason}", 502)
    dataset, recs = records_from_payload(payload)
    return {"dataset": dataset if dataset != "UPLOAD" else group_id,
            "imported": import_records(dataset if dataset != "UPLOAD" else group_id, recs)}


# ------------------------------------------------------------------ evaluation
def run_evaluation(conversation_id, checklist_id, mode="auto"):
    conv = store.get_conversation(conversation_id)
    if not conv:
        bad(f"Диалог {conversation_id} не найден", 404)
    cl = store.get_checklist(checklist_id) if checklist_id else store.default_checklist()
    if not cl:
        bad("Чек-лист не найден", 404)
    try:
        ev = evaluator.evaluate(conv, cl, mode)
    except llm.LLMError as e:
        bad(f"Ошибка LLM: {e}", 502)
    ev = store.save_evaluation(ev)
    return evaluator.to_view(ev, [])


def evaluation_view(eid):
    ev = store.get_evaluation(eid)
    if not ev:
        bad("Оценка не найдена", 404)
    return evaluator.to_view(ev, store.list_appeals(evaluation_id=eid))


def start_batch(checklist_id, conversation_ids, mode):
    job_id = "job_" + uuid.uuid4().hex[:8]
    job = {"id": job_id, "status": "running", "done": 0, "total": len(conversation_ids), "errors": [],
           "checklist_id": checklist_id, "results": {}}
    with jobs_lock:
        jobs[job_id] = job

    def one(cid):
        try:
            v = run_evaluation(cid, checklist_id, mode)
            res = {"evaluation_id": v["id"], "total": v["final"]["total"], "gross_error": v["final"]["gross_error"]}
        except Exception as e:  # noqa: BLE001
            msg = e.payload["error"] if isinstance(e, ApiError) else str(e)
            res = None
            with jobs_lock:
                job["errors"].append({"conversation_id": cid, "error": msg})
        with jobs_lock:
            job["done"] += 1
            if res:
                job["results"][cid] = res
            if job["done"] >= job["total"]:
                job["status"] = "done"

    if not conversation_ids:
        job["status"] = "done"
    for cid in conversation_ids:
        pool.submit(one, cid)
    return {"job_id": job_id, "total": job["total"]}


# ------------------------------------------------------------------ routes
ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


@route("GET", r"/api/health")
def r_health(h, body, q):
    return {"ok": True, "llm": llm.public_config(), "concurrency": CONCURRENCY,
            "datasets": store.datasets()}


@route("POST", r"/api/datasets/fetch")
def r_fetch(h, body, q):
    gid = (body or {}).get("group_id", "DEV").strip()
    if not gid:
        bad("Укажите group_id")
    return fetch_dataset(gid)


@route("POST", r"/api/conversations/import")
def r_import(h, body, q):
    dataset, recs = records_from_payload(body)
    if isinstance(body, dict) and body.get("dataset_override"):
        dataset = body["dataset_override"]
    return {"dataset": dataset, "imported": import_records(dataset, recs)}


@route("GET", r"/api/conversations")
def r_convs(h, body, q):
    return store.list_conversations(q.get("dataset"))


@route("GET", r"/api/conversations/(?P<cid>[^/]+)")
def r_conv(h, body, q, cid):
    c = store.get_conversation(cid)
    if not c:
        bad("Диалог не найден", 404)
    c["transcript"] = [{k: m[k] for k in ("index", "timestamp", "speaker", "text", "offset")}
                       for m in normalize(c["transcript"])]
    c["evaluations"] = [{"id": e["id"], "created_at": e["created_at"], "total": e["final_score"]["total"],
                         "original_total": e["score"]["total"], "gross_error": e["final_score"]["gross_error"],
                         "checklist_id": e["checklist_id"], "checklist_name": e["checklist_snapshot"].get("name"),
                         "checklist_version": e["checklist_snapshot"].get("version"), "engine": e["engine"]}
                        for e in reversed(store.list_evaluations(cid))]  # от старых к новым: UI берёт последнюю
    # Запись звонка отдаём через свой прокси: исходник — эндпоинт Power Automate, а не mp3
    c["audio_src"] = f"/api/audio/{urllib.parse.quote(cid)}" if c.get("audio_url") else None
    return c


@route("GET", r"/api/checklists")
def r_cls(h, body, q):
    return store.list_checklists(include_archived=q.get("archived") == "1")


@route("GET", r"/api/checklists/(?P<cid>[^/]+)")
def r_cl(h, body, q, cid):
    c = store.get_checklist(cid)
    if not c:
        bad("Чек-лист не найден", 404)
    return c


def _validated(body):
    if not isinstance(body, dict):
        bad("Ожидался JSON-объект чек-листа")
    for c in body.get("criteria", []):
        if c.get("type") == "scale":
            for s in c.get("scale", []):
                try:
                    s["value"] = float(s["value"])
                    if s["value"].is_integer():
                        s["value"] = int(s["value"])
                except (TypeError, ValueError, KeyError):
                    pass
        if "weight" in c:
            try:
                c["weight"] = float(c["weight"])
                if c["weight"].is_integer():
                    c["weight"] = int(c["weight"])
            except (TypeError, ValueError):
                pass
        if c.get("type") == "flag":
            c["weight"], c["na_allowed"] = 0, False
    errs = scoring.validate_checklist(body)
    if errs:
        raise ApiError(400, {"error": "Чек-лист не прошёл проверку", "errors": errs})
    return body


@route("POST", r"/api/checklists")
def r_cl_create(h, body, q):
    return store.save_checklist(_validated(body), make_default=bool(body.get("make_default")))


@route("PUT", r"/api/checklists/(?P<cid>[^/]+)")
def r_cl_update(h, body, q, cid):
    if not store.get_checklist(cid):
        bad("Чек-лист не найден", 404)
    return store.save_checklist(_validated(body), checklist_id=cid, make_default=bool(body.get("make_default")))


@route("POST", r"/api/checklists/(?P<cid>[^/]+)/default")
def r_cl_default(h, body, q, cid):
    if not store.get_checklist(cid):
        bad("Чек-лист не найден", 404)
    store.set_default(cid)
    return {"ok": True}


@route("DELETE", r"/api/checklists/(?P<cid>[^/]+)")
def r_cl_delete(h, body, q, cid):
    store.archive_checklist(cid)
    return {"ok": True}


@route("POST", r"/api/evaluate")
def r_eval(h, body, q):
    body = body or {}
    if not body.get("conversation_id"):
        bad("Укажите conversation_id")
    return run_evaluation(body["conversation_id"], body.get("checklist_id"), body.get("mode", "auto"))


@route("POST", r"/api/evaluate/batch")
def r_batch(h, body, q):
    body = body or {}
    cl = store.get_checklist(body["checklist_id"]) if body.get("checklist_id") else store.default_checklist()
    if not cl:
        bad("Чек-лист не найден", 404)
    ids = body.get("conversation_ids")
    if not ids:
        ids = [c["conversation_id"] for c in store.list_conversations(body.get("dataset"))]
        if body.get("only_unevaluated"):
            ids = [i for i in ids if not store.latest_evaluation(i, cl["id"])]
    return start_batch(cl["id"], ids, body.get("mode", "auto"))


@route("GET", r"/api/jobs/(?P<jid>[^/]+)")
def r_job(h, body, q, jid):
    with jobs_lock:
        j = jobs.get(jid)
        if not j:
            bad("Задача не найдена", 404)
        return json.loads(json.dumps(j))


@route("GET", r"/api/evaluations/(?P<eid>[^/]+)")
def r_ev(h, body, q, eid):
    return evaluation_view(eid)


@route("POST", r"/api/appeals")
def r_appeal(h, body, q):
    body = body or {}
    ev = store.get_evaluation(body.get("evaluation_id", ""))
    if not ev:
        bad("Оценка не найдена", 404)
    cid = body.get("criterion_id")
    if cid not in {c["id"] for c in ev["checklist_snapshot"]["criteria"]}:
        bad("Критерий не найден в оценке")
    if not str(body.get("comment", "")).strip():
        bad("Добавьте комментарий к апелляции")
    if any(a["criterion_id"] == cid and a["status"] == "open"
           for a in store.list_appeals(evaluation_id=ev["id"])):
        bad("По этому критерию уже есть открытая апелляция", 409)
    return store.create_appeal(ev["id"], ev["conversation_id"], cid, body["comment"].strip(),
                               body.get("author") or "Пользователь")


@route("GET", r"/api/appeals")
def r_appeals(h, body, q):
    out = []
    cache = {}
    for a in store.list_appeals(q.get("status")):
        ev = cache.get(a["evaluation_id"]) or store.get_evaluation(a["evaluation_id"])
        cache[a["evaluation_id"]] = ev
        if not ev:
            continue
        c = next((x for x in ev["checklist_snapshot"]["criteria"] if x["id"] == a["criterion_id"]), {})
        o = next((r for r in ev["results"] if r["criterion_id"] == a["criterion_id"]), {})
        a.update({"criterion_title": c.get("title"), "criterion_code": c.get("code"),
                  "original_answer": o.get("answer"), "evaluation_total": ev["final_score"]["total"],
                  "checklist_name": ev["checklist_snapshot"].get("name")})
        out.append(a)
    return out


@route("GET", r"/api/appeals/(?P<aid>[^/]+)")
def r_appeal_get(h, body, q, aid):
    a = store.get_appeal(aid)
    if not a:
        bad("Апелляция не найдена", 404)
    return {"appeal": a, "evaluation": evaluation_view(a["evaluation_id"])}


@route("POST", r"/api/appeals/(?P<aid>[^/]+)/decision")
def r_decide(h, body, q, aid):
    body = body or {}
    a = store.get_appeal(aid)
    if not a:
        bad("Апелляция не найдена", 404)
    if a["status"] != "open":
        bad("Апелляция уже рассмотрена", 409)
    action = body.get("action")
    if action not in ("confirm", "change"):
        bad("action должен быть confirm или change")
    if not str(body.get("reason", "")).strip():
        bad("Укажите причину решения")
    ev = store.get_evaluation(a["evaluation_id"])
    prev = next(r for r in ev["final_results"] if r["criterion_id"] == a["criterion_id"])["answer"]
    decision = {"action": action, "new_answer": body.get("new_answer") if action == "change" else prev,
                "previous_answer": prev, "reason": body["reason"].strip(),
                "reviewer": body.get("reviewer") or "Проверяющий",
                "total_before": ev["final_score"]["total"]}
    try:
        ev = evaluator.apply_decision(ev, a["criterion_id"], body.get("new_answer"), decision)
    except ValueError as e:
        bad(str(e))
    decision["new_answer"] = next(r for r in ev["final_results"] if r["criterion_id"] == a["criterion_id"])["answer"]
    decision["total_after"] = ev["final_score"]["total"]
    for r in ev["final_results"]:
        if r["criterion_id"] == a["criterion_id"]:
            r["decision"] = decision
    store.save_evaluation(ev)
    appeal = store.decide_appeal(aid, decision)
    return {"appeal": appeal, "evaluation": evaluation_view(ev["id"])}


# ------------------------------------------------------------------ audio
AUDIO_DIR = os.path.join(ROOT, "data", "audio")
_audio_lock = threading.Lock()
_MAGIC = [(b"ID3", "audio/mpeg"), (b"\xff\xfb", "audio/mpeg"), (b"\xff\xf3", "audio/mpeg"),
          (b"\xff\xf2", "audio/mpeg"), (b"RIFF", "audio/wav"), (b"OggS", "audio/ogg"),
          (b"fLaC", "audio/flac"), (b"\x1aE\xdf\xa3", "audio/webm")]


def sniff_audio_type(data: bytes, fallback: str = "application/octet-stream") -> str:
    for sig, ctype in _MAGIC:
        if data.startswith(sig):
            return ctype
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    return fallback


def unwrap_audio(data: bytes, ctype: str):
    """Power Automate часто отдаёт файл в JSON-обёртке {"$content-type": ..., "$content": base64}
    или ссылку на файл. Возвращает (bytes, content_type) либо (None, url) для повторного запроса."""
    head = data[:4096].lstrip().lower()
    if "html" in ctype or head.startswith((b"<!doctype html", b"<html")):
        # Power Automate отдаёт страницу-плеер: <audio><source src="...dynamics.com/...">
        import html as _html
        m = re.search(rb"""<(?:source|audio)\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", data, re.I)
        if not m:
            bad("Страница записи не содержит ссылки на аудио", 502)
        return None, _html.unescape(m.group(1).decode("utf-8", "replace"))
    if data[:1] in (b"{", b"[") or "json" in ctype:
        import base64
        try:
            obj = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return data, sniff_audio_type(data, ctype)
        stack = [obj]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if "$content" in o:
                    raw = base64.b64decode(o["$content"])
                    return raw, sniff_audio_type(raw, o.get("$content-type") or "audio/mpeg")
                for k in ("url", "audio_url", "downloadUrl", "link"):
                    if isinstance(o.get(k), str) and o[k].startswith("http"):
                        return None, o[k]
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
        bad("Ответ источника записи не содержит аудио", 502)
    return data, sniff_audio_type(data, ctype.split(";")[0].strip() or "application/octet-stream")


def load_audio(cid: str):
    """Скачивает запись звонка один раз и кэширует в data/audio/. Возвращает (path, content_type)."""
    c = store.get_conversation(cid)
    if not c or not c.get("audio_url"):
        bad("У диалога нет записи", 404)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", cid)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    meta_path = os.path.join(AUDIO_DIR, safe + ".type")
    path = os.path.join(AUDIO_DIR, safe + ".bin")
    with _audio_lock:
        if os.path.exists(path) and os.path.exists(meta_path):
            return path, open(meta_path, encoding="utf-8").read().strip()
        url = c["audio_url"]
        for _ in range(3):
            req = urllib.request.Request(url, headers={"User-Agent": "CQA/1.0", "Accept": "audio/*,*/*"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data, ctype = r.read(), r.headers.get("Content-Type", "")
            except urllib.error.HTTPError as e:
                bad(f"Источник записи ответил {e.code}", 502)
            except urllib.error.URLError as e:
                bad(f"Источник записи недоступен: {e.reason}", 502)
            data, ctype = unwrap_audio(data, ctype)
            if data is not None:
                break
            url = ctype  # пришла ссылка на файл — идём по ней
        else:
            bad("Слишком много перенаправлений к записи", 502)
        with open(path, "wb") as f:
            f.write(data)
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(ctype)
        return path, ctype


# ------------------------------------------------------------------ http
class Handler(SimpleHTTPRequestHandler):
    server_version = "CQA/1.0"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    def log_message(self, fmt, *args):
        if os.environ.get("CQA_QUIET") != "1":
            sys.stderr.write("%s %s\n" % (self.command, fmt % args))

    def _send(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _api(self, method):
        parts = urllib.parse.urlsplit(self.path)
        path = parts.path.rstrip("/") or "/"
        q = dict(urllib.parse.parse_qsl(parts.query))
        body = None
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._send(400, {"error": "Некорректный JSON в теле запроса"})
        for m, rx, fn in ROUTES:
            if m != method:
                continue
            mt = rx.match(path)
            if mt:
                try:
                    kw = {k: urllib.parse.unquote(v) for k, v in mt.groupdict().items()}
                    return self._send(200, fn(self, body, q, **kw))
                except ApiError as e:
                    return self._send(e.status, e.payload)
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    return self._send(500, {"error": f"Внутренняя ошибка: {e}"})
        return self._send(404, {"error": f"Нет маршрута {method} {path}"})

    def _audio(self, cid):
        try:
            path, ctype = load_audio(cid)
        except ApiError as e:
            return self._send(e.status, e.payload)
        size = os.path.getsize(path)
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(0, size - int(m.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            self.wfile.write(f.read(end - start + 1))

    def do_GET(self):
        if self.path.startswith("/api/audio/"):
            return self._audio(urllib.parse.unquote(urllib.parse.urlsplit(self.path).path[len("/api/audio/"):]))
        if self.path.startswith("/api/"):
            return self._api("GET")
        return super().do_GET()

    def do_POST(self):
        return self._api("POST")

    def do_PUT(self):
        return self._api("PUT")

    def do_DELETE(self):
        return self._api("DELETE")

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main():
    host = os.environ.get("CQA_HOST", "127.0.0.1")
    port = int(os.environ.get("CQA_PORT", "8000"))
    if len(sys.argv) > 1 and sys.argv[1] == "--seed-demo":
        with open(os.path.join(ROOT, "data", "demo_dataset.json"), encoding="utf-8") as f:
            ds, recs = records_from_payload(json.load(f))
        print(f"Демо-набор: импортировано {import_records(ds, recs)} диалогов")
    os.makedirs(WEB_DIR, exist_ok=True)
    cfg = llm.public_config()
    print(f"CQA: http://{host}:{port}  |  LLM: {cfg['provider']} {cfg['model'] if cfg['enabled'] else '(офлайн-режим)'}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
