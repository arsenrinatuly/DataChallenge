"""Нормализация транскрипта и вычисляемые факты (паузы, первая реакция)."""
from __future__ import annotations

import re
from datetime import datetime

ROLE_ALIASES = {
    "agent": "operator", "оператор": "operator", "operator": "operator", "manager": "operator",
    "client": "client", "customer": "client", "клиент": "client", "user": "client",
    "bot": "bot", "бот": "bot", "system": "system", "система": "system",
}


def parse_ts(ts) -> float | None:
    """MM:SS / HH:MM:SS -> секунды; ISO 8601 -> epoch seconds."""
    if ts is None:
        return None
    s = str(ts).strip()
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,3}):(\d{2})(?:\.\d+)?", s)
    if m:
        h, mm, ss = m.groups()
        return int(h or 0) * 3600 + int(mm) * 60 + int(ss)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def normalize(transcript: list) -> list[dict]:
    msgs = []
    base = None
    for i, m in enumerate(transcript or []):
        speaker = ROLE_ALIASES.get(str(m.get("speaker", "")).strip().lower(), str(m.get("speaker", "")).lower())
        t = parse_ts(m.get("timestamp"))
        if base is None and t is not None:
            base = t
        msgs.append({
            "index": i,
            "timestamp": m.get("timestamp"),
            "speaker": speaker,
            "text": str(m.get("text") or ""),
            "t": t,
            "offset": (t - base) if (t is not None and base is not None) else None,
        })
    return msgs


def fmt_dur(sec: float | None) -> str:
    if sec is None:
        return "?"
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


WAIT_WORDS = [
    # RU
    "подожд", "ожидайт", "минуту", "минутку", "секунду", "уточню", "уточняю", "проверю", "проверяю",
    "оставайтесь на связи", "сейчас посмотрю", "немного времени",
    # KZ
    "күте тұрыңыз", "күтіңіз", "бір минут", "бір сәт", "тексеремін", "нақтылаймын", "тексеріп",
    # EN
    "please wait", "one moment", "a moment", "let me check", "bear with me", "hold on", "give me a minute",
    "i'll check", "checking",
]


ESCALATION_WORDS = [
    "эскалация на оператора", "переведен от агента", "переведён от агента", "агент присоединился",
    "операторға жіберілді", "операторға қосылды", "transferred to an agent", "agent joined",
]


def escalation_index(msgs: list[dict]) -> int | None:
    """Индекс системного события передачи диалога оператору (до него клиент общался с ботом)."""
    first_op = next((m["index"] for m in msgs if m["speaker"] == "operator"), None)
    cands = [m["index"] for m in msgs if m["speaker"] == "system"
             and any(w in m["text"].lower() for w in ESCALATION_WORDS)
             and (first_op is None or m["index"] < first_op)]
    return cands[-1] if cands else None


def response_facts(msgs: list[dict], threshold: int | None = None, wait_gap: int = 180) -> dict:
    """Первая реакция оператора (от передачи диалога оператору) и паузы дольше порога."""
    facts = {"threshold_sec": threshold, "wait_gap_sec": wait_gap, "first_response": None, "long_gaps": [],
             "escalation_index": None}
    esc = escalation_index(msgs)
    facts["escalation_index"] = esc
    start = msgs[esc] if esc is not None else next((m for m in msgs if m["speaker"] == "client"), None)
    if start and start["t"] is not None:
        op = next((m for m in msgs if m["speaker"] == "operator" and m["index"] > start["index"]
                   and m["t"] is not None), None)
        if op:
            gap = op["t"] - start["t"]
            facts["first_response"] = {"client_index": start["index"], "operator_index": op["index"],
                                       "from": "escalation" if esc is not None else "first_client_message",
                                       "seconds": gap, "exceeds": bool(threshold) and gap > threshold}
    # Паузы после подключения оператора: от реплики клиента (или «подождите») до следующей реплики оператора
    first_op = facts["first_response"]["operator_index"] if facts["first_response"] else None
    pending = None
    for m in msgs:
        if first_op is None or m["index"] <= first_op:
            continue
        if m["t"] is None:
            continue
        if m["speaker"] == "client" and pending is None:
            pending = m
        elif m["speaker"] == "operator":
            if pending is not None:
                gap = m["t"] - pending["t"]
                if gap > wait_gap:
                    warned = any(
                        x["speaker"] == "operator" and any(w in x["text"].lower() for w in WAIT_WORDS)
                        for x in msgs if pending["index"] - 3 <= x["index"] < m["index"])
                    facts["long_gaps"].append({"from_index": pending["index"], "to_index": m["index"],
                                               "seconds": gap, "operator_warned": warned})
            pending = None
            low = m["text"].lower()
            if any(w in low for w in WAIT_WORDS):
                pending = m  # после «подождите» отсчитываем ожидание заново
    return facts


def render_for_prompt(msgs: list[dict]) -> str:
    lines = []
    for m in msgs:
        ts = m["timestamp"] if m["timestamp"] is not None else ""
        lines.append(f"[{m['index']}] ({ts}) {m['speaker']}: {m['text']}")
    return "\n".join(lines)
