"""Детерминированный расчёт итога по чек-листу.

Правила (из PDF «Чек-лист качества чатов», стр. 2):
1. N/A только там, где он разрешён.
2. «Да» = полный вес, «Нет» = 0. Шкала — одна из указанных ступеней.
3. Шкальная оценка пересчитывается пропорционально весу: верхняя ступень = полный вес.
4. Критерии с N/A исключаются, их вес пропорционально перераспределяется
   между применимыми критериями. Максимум остаётся 100.
5. Округление итога до `rounding` знаков. Если применимых критериев с весом нет —
   итог не рассчитывается. Грубые ошибки (type=flag) отмечаются отдельно.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

NA = "na"
YES = "yes"
NO = "no"


def _round(value: float, digits: int) -> float:
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def scale_values(criterion: dict) -> list[int | float]:
    return sorted({s["value"] for s in criterion.get("scale", [])}, reverse=True)


def allowed_answers(criterion: dict) -> list:
    t = criterion["type"]
    if t == "scale":
        vals = list(scale_values(criterion))
    elif t == "flag":
        vals = [YES, NO]
    else:
        vals = [YES, NO]
    if criterion.get("na_allowed") and t != "flag":
        vals.append(NA)
    return vals


def normalize_answer(criterion: dict, answer):
    """Приводит ответ к допустимому значению. Возвращает (answer, warning|None)."""
    t = criterion["type"]
    if isinstance(answer, str):
        a = answer.strip().lower()
        if a in ("n/a", "na", "н/п", "n.a.", "не применимо", "неприменимо"):
            answer = NA
        elif a in ("да", "yes", "иә", "true"):
            answer = YES
        elif a in ("нет", "no", "жоқ", "false"):
            answer = NO
        else:
            try:
                answer = float(a)
            except ValueError:
                answer = a
    if answer is None:
        answer = NA
    if answer == NA:
        if criterion.get("na_allowed") and t != "flag":
            return NA, None
        fallback = NO if t != "scale" else min(scale_values(criterion) or [0])
        return fallback, "N/A не разрешён для критерия — заменено на минимальную оценку"
    if t == "scale":
        steps = scale_values(criterion)
        if answer in (YES, NO):
            answer = max(steps) if answer == YES else min(steps)
        try:
            v = float(answer)
        except (TypeError, ValueError):
            return min(steps), f"Недопустимое значение шкалы {answer!r}"
        nearest = min(steps, key=lambda s: (abs(s - v), -s))
        nearest = int(nearest) if float(nearest).is_integer() else nearest
        return nearest, (None if nearest == v else f"Значение {v} приведено к ступени {nearest}")
    if answer in (YES, NO):
        return answer, None
    if isinstance(answer, (int, float)):
        return (YES if answer > 0 else NO), "Числовой ответ для бинарного критерия"
    return NO, f"Недопустимый ответ {answer!r}"


def raw_points(criterion: dict, answer) -> float | None:
    """Баллы до перераспределения N/A. None — критерий исключён."""
    weight = float(criterion.get("weight", 0))
    t = criterion["type"]
    if t == "flag" or answer == NA:
        return None
    if t == "scale":
        top = max(scale_values(criterion) or [1])
        return weight * float(answer) / float(top) if top else 0.0
    return weight if answer == YES else 0.0


def compute(checklist: dict, answers: dict) -> dict:
    """answers: {criterion_id: answer}. Возвращает итог, секции и баллы по критериям."""
    digits = int(checklist.get("rounding", 2))
    rows = []
    applicable_weight = 0.0
    gross = False
    gross_criteria = []
    for c in checklist["criteria"]:
        a = answers.get(c["id"], NA)
        if c["type"] == "flag":
            if a == YES:
                gross = True
                gross_criteria.append(c["id"])
            rows.append({"criterion_id": c["id"], "answer": a, "weight": 0,
                         "applicable": False, "raw_points": None, "points": None,
                         "effective_weight": 0})
            continue
        rp = raw_points(c, a)
        w = float(c.get("weight", 0))
        applicable = rp is not None and w > 0
        if applicable:
            applicable_weight += w
        rows.append({"criterion_id": c["id"], "answer": a, "weight": w,
                     "applicable": applicable, "raw_points": rp,
                     "points": None, "effective_weight": 0})

    if applicable_weight <= 0:
        total = None
        factor = 0.0
    else:
        factor = 100.0 / applicable_weight
        total_raw = sum(r["raw_points"] for r in rows if r["applicable"])
        total = _round(total_raw * factor, digits)

    for r in rows:
        if r["applicable"]:
            r["points"] = _round(r["raw_points"] * factor, digits)
            r["effective_weight"] = _round(r["weight"] * factor, digits)
            r["raw_points"] = _round(r["raw_points"], digits)

    sections = []
    by_id = {r["criterion_id"]: r for r in rows}
    for s in checklist.get("sections", []):
        crit = [c for c in checklist["criteria"] if c.get("section") == s["id"]]
        app = [by_id[c["id"]] for c in crit if by_id[c["id"]]["applicable"]]
        if not crit or all(c["type"] == "flag" for c in crit):
            continue
        if not app:
            sections.append({"id": s["id"], "title": s["title"], "points": None,
                             "max": 0, "percent": None})
            continue
        pts = sum(r["raw_points"] for r in app) * factor
        mx = sum(r["weight"] for r in app) * factor
        sections.append({"id": s["id"], "title": s["title"],
                         "points": _round(pts, digits), "max": _round(mx, digits),
                         "percent": _round(100 * pts / mx, digits) if mx else None})

    return {
        "total": total,
        "max": 100 if total is not None else None,
        "applicable_weight": applicable_weight,
        "redistribution_factor": _round(factor, 6) if factor else None,
        "gross_error": gross,
        "gross_criteria": gross_criteria,
        "criteria": rows,
        "sections": sections,
    }


def validate_checklist(cl: dict) -> list[str]:
    errors = []
    if not cl.get("name"):
        errors.append("Нет названия чек-листа")
    ids = set()
    sections = {s["id"] for s in cl.get("sections", [])}
    for i, c in enumerate(cl.get("criteria", [])):
        label = c.get("code") or c.get("id") or f"#{i+1}"
        if not c.get("id"):
            errors.append(f"Критерий {label}: нет id")
        if c.get("id") in ids:
            errors.append(f"Критерий {label}: повторяющийся id")
        ids.add(c.get("id"))
        if not c.get("title"):
            errors.append(f"Критерий {label}: нет названия")
        if c.get("type") not in ("binary", "scale", "flag"):
            errors.append(f"Критерий {label}: тип должен быть binary, scale или flag")
        try:
            w = float(c.get("weight", 0))
            if w < 0:
                errors.append(f"Критерий {label}: вес не может быть отрицательным")
        except (TypeError, ValueError):
            errors.append(f"Критерий {label}: вес должен быть числом")
        if c.get("type") == "scale":
            sc = c.get("scale") or []
            if len(sc) < 2:
                errors.append(f"Критерий {label}: у шкалы должно быть минимум 2 ступени")
            vals = [s.get("value") for s in sc]
            if any(not isinstance(v, (int, float)) for v in vals):
                errors.append(f"Критерий {label}: значения шкалы должны быть числами")
            elif len(set(vals)) != len(vals):
                errors.append(f"Критерий {label}: значения шкалы повторяются")
            elif vals and max(vals) <= 0:
                errors.append(f"Критерий {label}: верхняя ступень шкалы должна быть > 0")
        if c.get("section") and sections and c["section"] not in sections:
            errors.append(f"Критерий {label}: секция {c['section']} не найдена")
    if not cl.get("criteria"):
        errors.append("В чек-листе нет критериев")
    return errors
