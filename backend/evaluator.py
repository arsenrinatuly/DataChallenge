"""Оценка диалога: LLM выставляет ответы и доказательства, код считает баллы."""
from __future__ import annotations

import copy
import json
import time

from . import heuristic, llm, scoring
from .transcript import fmt_dur, normalize, render_for_prompt, response_facts

SYSTEM_PROMPT = """Ты — эксперт службы контроля качества брокерской компании Freedom Broker.
Ты оцениваешь работу ОПЕРАТОРА в диалоге с клиентом строго по чек-листу.

Правила:
- Оценивай только реплики с ролью operator. Реплики bot и system — контекст (например, system может
  подтверждать, что клиент прошёл идентификацию, или что клиент покинул чат).
- Диалог может быть на русском, казахском или английском. Язык клиента определяй по его репликам.
- Для каждого критерия выбери ответ ТОЛЬКО из списка допустимых значений.
- N/A ставь только если он разрешён И выполнено условие N/A. «Нет» — действие было нужно, но оператор его
  пропустил или выполнил неправильно.
- Для шкальных критериев выбери одну из указанных ступеней (число).
- evidence — реплики, подтверждающие вывод: номер реплики [index] и короткая точная цитата из неё (до 20 слов).
- Если действие пропущено — укажи checked_range: диапазон реплик, где действие ожидалось.
- Если ответ N/A — заполни na_reason: какое условие неприменимости выполнено.
- explanation — 1–2 предложения на русском, по делу, со ссылкой на конкретные реплики.
- confidence — уверенность от 0 до 1.
- Для критерия-флага (type=flag) ответ "yes" означает, что нарушение ВЫЯВЛЕНО.
- Предложение услуги в обход компании: достаточно самого предложения (перевести деньги оператору лично,
  личный номер для платной консультации). Согласие клиента не требуется.
- Теги и вложения в оценку не входят.
- До системного события передачи оператору (эскалация, «Агент присоединился» и т.п.) клиент общался с ботом.
  Всё, что клиент написал боту, оператору УЖЕ ИЗВЕСТНО: если оператор переспрашивает уже сказанное
  или спрашивает «Чем могу помочь?», хотя запрос написан выше, — это не выявление потребности.
- Время реакции оператора считается от передачи диалога оператору, а не от первой реплики клиента боту.
  Используй вычисленные факты о времени, не пересчитывай их сам. Если в фактах сказано, что время первой
  реакции в оценку не входит, — не снижай за него оценку.
- Звонки — автоматическая расшифровка речи с ошибками распознавания: не снижай оценку за искажённые слова.
  Данные вида «[Персональные данные скрыты]» / «[Данные идентификации скрыты]» — замаскированные реальные данные:
  если оператор запросил их и подтвердил идентификацию, проверка личности пройдена.
  Реплики оператора, адресованные коллеге во время удержания клиента (консультация с агентом), клиент не слышит.

Ответь ТОЛЬКО JSON-объектом без пояснений вокруг, формат:
{"criteria":[{"criterion_id":"...","answer":"yes|no|na|<число>","explanation":"...",
"evidence":[{"index":0,"quote":"..."}],"checked_range":{"from":0,"to":0}|null,"na_reason":null|"...",
"confidence":0.0}]}"""


def _criteria_block(checklist: dict) -> str:
    out = []
    for c in checklist["criteria"]:
        allowed = scoring.allowed_answers(c)
        lines = [f"- criterion_id: {c['id']} | {c.get('code', '')} {c['title']}",
                 f"  type: {c['type']}; допустимые ответы: {json.dumps(allowed, ensure_ascii=False)}"]
        if c.get("yes_rule"):
            lines.append(f"  правило: {c['yes_rule']}")
        if c.get("na_allowed") and c.get("na_rule"):
            lines.append(f"  условие N/A: {c['na_rule']}")
        if c["type"] == "scale":
            for s in sorted(c.get("scale", []), key=lambda s: -s["value"]):
                lines.append(f"    {s['value']} — {s['label']}")
        out.append("\n".join(lines))
    return "\n".join(out)


def _facts_block(facts: dict, msgs) -> str:
    lines = [f"Порог первой реакции оператора: {fmt_dur(facts['threshold_sec'])}." if facts.get("threshold_sec")
             else "Время первой реакции в оценку не входит (приведено только для контекста)."]
    fr = facts.get("first_response")
    if fr:
        src = "передача оператору" if fr.get("from") == "escalation" else "первая реплика клиента"
        lines.append(f"Первая реакция оператора: {fmt_dur(fr['seconds'])} ({src} [{fr['client_index']}] → "
                     f"оператор [{fr['operator_index']}]){' — ПРЕВЫШЕН порог' if fr['exceeds'] else ''}.")
    for g in facts.get("long_gaps", []):
        lines.append(f"Пауза {fmt_dur(g['seconds'])} между [{g['from_index']}] и ответом оператора [{g['to_index']}]; "
                     f"предупреждение об ожидании: {'было' if g['operator_warned'] else 'не найдено'}.")
    if not fr and not facts.get("long_gaps"):
        lines.append("Пауз дольше порога ожидания посреди диалога нет.")
    return "\n".join(lines)


def build_prompt(conv: dict, checklist: dict, msgs, facts) -> str:
    return (f"Канал: {conv.get('channel')}; язык набора: {conv.get('language')}.\n"
            f"Примечания к чек-листу: {checklist.get('notes', '')}\n\n"
            f"КРИТЕРИИ:\n{_criteria_block(checklist)}\n\n"
            f"ВЫЧИСЛЕННЫЕ ФАКТЫ О ВРЕМЕНИ:\n{_facts_block(facts, msgs)}\n\n"
            f"ДИАЛОГ (формат: [index] (timestamp) speaker: text):\n{render_for_prompt(msgs)}")


def _clean_result(c: dict, raw: dict, msgs) -> tuple[dict, list[str]]:
    warnings = []
    answer, w = scoring.normalize_answer(c, raw.get("answer"))
    if w:
        warnings.append(w)
    n = len(msgs)
    evidence = []
    for e in raw.get("evidence") or []:
        try:
            i = int(e.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= i < n:
            q = str(e.get("quote") or "").strip()
            if not q or q.lower()[:25] not in msgs[i]["text"].lower():
                q = msgs[i]["text"][:140] + ("…" if len(msgs[i]["text"]) > 140 else "")
            evidence.append({"index": i, "quote": q})
    cr = raw.get("checked_range")
    if isinstance(cr, dict):
        try:
            f, t = max(0, int(cr.get("from"))), min(n - 1, int(cr.get("to")))
            cr = {"from": min(f, t), "to": max(f, t)} if n else None
        except (TypeError, ValueError):
            cr = None
    else:
        cr = None
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence", 0.7))))
    except (TypeError, ValueError):
        conf = 0.7
    na_reason = raw.get("na_reason") if answer == scoring.NA else None
    if answer == scoring.NA and not na_reason:
        na_reason = c.get("na_rule") or "Критерий неприменим."
    if answer in (scoring.NO, 0) and not cr and not evidence and n:
        cr = {"from": 0, "to": n - 1}
    return ({"criterion_id": c["id"], "answer": answer,
             "explanation": str(raw.get("explanation") or "").strip(),
             "evidence": evidence, "checked_range": cr, "na_reason": na_reason,
             "confidence": conf, "source": "llm"}, warnings)


def evaluate(conv: dict, checklist: dict, mode: str = "auto") -> dict:
    """mode: auto (LLM если настроен, иначе правила) | llm | heuristic."""
    started = time.time()
    msgs = normalize(conv["transcript"])
    thr = checklist.get("first_response_threshold_sec")
    facts = response_facts(msgs, int(thr) if thr else None, int(checklist.get("wait_gap_sec") or 180))
    meta = {"facts": facts, "warnings": [], "llm": None}
    results = {}
    use_llm = mode == "llm" or (mode == "auto" and llm.config()["enabled"])
    engine = "heuristic"

    if use_llm:
        prompt = build_prompt(conv, checklist, msgs, facts)
        try:
            resp = llm.chat(SYSTEM_PROMPT, prompt)
            usage = [resp]
            try:
                data = llm.extract_json(resp["text"])
            except (llm.LLMError, json.JSONDecodeError):
                resp2 = llm.chat(SYSTEM_PROMPT, prompt + "\n\nВерни строго валидный JSON по формату.")
                usage.append(resp2)
                data = llm.extract_json(resp2["text"])
            raw_by_id = {str(r.get("criterion_id")): r for r in data.get("criteria", []) if isinstance(r, dict)}
            for c in checklist["criteria"]:
                if c["id"] in raw_by_id:
                    res, w = _clean_result(c, raw_by_id[c["id"]], msgs)
                    results[c["id"]] = res
                    meta["warnings"] += [f"{c.get('code', c['id'])}: {x}" for x in w]
            engine = f"llm:{resp['model']}"
            meta["llm"] = {"provider": resp["provider"], "model": resp["model"],
                           "calls": len(usage),
                           "input_tokens": sum(u["input_tokens"] for u in usage),
                           "output_tokens": sum(u["output_tokens"] for u in usage),
                           "cost_usd": round(sum(u["cost_usd"] for u in usage), 6)}
        except (llm.LLMError, json.JSONDecodeError, KeyError) as e:
            if mode == "llm":
                raise
            meta["warnings"].append(f"LLM недоступен, использован офлайн-режим: {e}")

    for c in checklist["criteria"]:
        if c["id"] not in results:
            r = heuristic.evaluate_rule(c, msgs, conv.get("language"), facts)
            r["answer"], _ = scoring.normalize_answer(c, r["answer"])
            r["source"] = "heuristic"
            results[c["id"]] = r
            if engine != "heuristic":
                meta["warnings"].append(f"{c.get('code', c['id'])}: модель не вернула ответ, применены правила")

    ordered = [results[c["id"]] for c in checklist["criteria"]]
    score = scoring.compute(checklist, {r["criterion_id"]: r["answer"] for r in ordered})
    meta["duration_sec"] = round(time.time() - started, 2)
    return {
        "conversation_id": conv["conversation_id"],
        "checklist_id": checklist["id"],
        "checklist_snapshot": checklist,
        "results": ordered,
        "score": score,
        "final_results": copy.deepcopy(ordered),
        "final_score": score,
        "engine": engine,
        "meta": meta,
    }


def apply_decision(ev: dict, criterion_id: str, new_answer, decision: dict) -> dict:
    cl = ev["checklist_snapshot"]
    c = next(x for x in cl["criteria"] if x["id"] == criterion_id)
    for r in ev["final_results"]:
        if r["criterion_id"] == criterion_id:
            if decision["action"] == "change":
                ans, w = scoring.normalize_answer(c, new_answer)
                if w:
                    raise ValueError(w)
                r["answer"] = ans
                if ans == scoring.NA:
                    r["na_reason"] = decision.get("reason")
            r["decision"] = decision
    ev["final_score"] = scoring.compute(cl, {r["criterion_id"]: r["answer"] for r in ev["final_results"]})
    return ev


def _pts(score, cid):
    row = next((r for r in score["criteria"] if r["criterion_id"] == cid), None)
    return row or {}


_REF = __import__("re").compile(r"\[(\d{1,4})\]")


def human_refs(text):
    """Модель ссылается на реплики по индексу с нуля ([9]), а интерфейс нумерует с единицы (#10)."""
    return _REF.sub(lambda m: f"#{int(m.group(1)) + 1}", text) if isinstance(text, str) else text


def to_view(ev: dict, appeals: list[dict]) -> dict:
    """Формирует объект Evaluation из API-контракта для фронтенда."""
    cl = ev["checklist_snapshot"]
    orig = {r["criterion_id"]: r for r in ev["results"]}
    fin = {r["criterion_id"]: r for r in ev["final_results"]}
    ap_by_c = {}
    for a in sorted(appeals, key=lambda a: a["created_at"]):
        ap_by_c[a["criterion_id"]] = a
    criteria = []
    for c in cl["criteria"]:
        o, f = orig.get(c["id"], {}), fin.get(c["id"], {})
        op, fp = _pts(ev["score"], c["id"]), _pts(ev["final_score"], c["id"])
        a = ap_by_c.get(c["id"])
        criteria.append({
            "criterion_id": c["id"], "code": c.get("code"), "title": c["title"],
            "section": c.get("section"), "type": c["type"], "weight": c.get("weight", 0),
            "na_allowed": c.get("na_allowed", False),
            "allowed_answers": scoring.allowed_answers(c),
            "original": {"answer": o.get("answer"), "points": op.get("points"),
                         "effective_weight": op.get("effective_weight"), "applicable": op.get("applicable")},
            "final": {"answer": f.get("answer"), "points": fp.get("points"),
                      "effective_weight": fp.get("effective_weight"), "applicable": fp.get("applicable")},
            "explanation": human_refs(o.get("explanation")), "evidence": o.get("evidence", []),
            "checked_range": o.get("checked_range"), "na_reason": human_refs(f.get("na_reason") or o.get("na_reason")),
            "confidence": o.get("confidence"), "source": o.get("source"),
            "appeal": None if not a else {"id": a["id"], "status": a["status"], "comment": a["comment"],
                                          "author": a["author"], "decision": a["decision"]},
        })

    def summary(s):
        return {"total": s["total"], "gross_error": s["gross_error"], "sections": s["sections"],
                "applicable_weight": s["applicable_weight"]}

    return {
        "id": ev["id"], "conversation_id": ev["conversation_id"], "checklist_id": ev["checklist_id"],
        "checklist_name": cl.get("name"), "checklist_version": cl.get("version"),
        "engine": ev["engine"], "created_at": ev["created_at"],
        "cost_usd": (ev["meta"].get("llm") or {}).get("cost_usd"),
        "llm_usage": ev["meta"].get("llm"), "warnings": ev["meta"].get("warnings", []),
        "facts": ev["meta"].get("facts"),
        "original": summary(ev["score"]), "final": summary(ev["final_score"]),
        "criteria": criteria,
    }
