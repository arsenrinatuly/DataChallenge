#!/usr/bin/env python3
"""Консольные команды без запуска сервера (удобно для контрольного набора на 23-м часу).

  python cli.py fetch DEV                  # скачать набор по group_id из API организаторов
  python cli.py import file.json           # импорт JSON-файла (формат API или массив records)
  python cli.py evaluate --dataset DEV     # оценить все диалоги набора чек-листом по умолчанию
  python cli.py evaluate --id p1-ru-001 --mode heuristic
  python cli.py report --dataset DEV       # таблица итогов
"""
import argparse
import json
import os
import sys

os.environ.setdefault("CQA_QUIET", "1")
import server  # noqa: E402  (подхватывает .env, БД и чек-лист по умолчанию)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("group_id")
    i = sub.add_parser("import")
    i.add_argument("path")
    i.add_argument("--dataset")
    e = sub.add_parser("evaluate")
    e.add_argument("--dataset")
    e.add_argument("--id", action="append")
    e.add_argument("--checklist")
    e.add_argument("--mode", default="auto", choices=["auto", "llm", "heuristic"])
    r = sub.add_parser("report")
    r.add_argument("--dataset")
    cp = sub.add_parser("compare", help="сравнить последние оценки с ручной разметкой (CSV)")
    cp.add_argument("gold", nargs="?", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                              "data", "gold_dev.csv"))
    cp.add_argument("--checklist", help="сравнивать только оценки этим чек-листом")
    cp.add_argument("--details", action="store_true", help="показать все расхождения с объяснениями")
    cp.add_argument("--out", help="сохранить расхождения в CSV")
    ex = sub.add_parser("export", help="выгрузить results.json в формате организаторов (JSON 1.0)")
    ex.add_argument("--dataset", required=True)
    ex.add_argument("--out", required=True, help="например results/dev/results.json")
    ex.add_argument("--checklist", help="брать оценки только этим чек-листом")
    ex.add_argument("--team", default="Gashtar")
    ex.add_argument("--model-name", default=os.environ.get("CQA_EXPORT_MODEL", ""),
                    help="по умолчанию берётся из оценок (CQA_LLM_MODEL)")
    a = ap.parse_args()

    if a.cmd == "export":
        export(a)
    elif a.cmd == "fetch":
        print(server.fetch_dataset(a.group_id))
    elif a.cmd == "import":
        with open(a.path, encoding="utf-8") as fh:
            ds, recs = server.records_from_payload(json.load(fh))
        print({"dataset": a.dataset or ds, "imported": server.import_records(a.dataset or ds, recs)})
    elif a.cmd == "evaluate":
        ids = a.id or [c["conversation_id"] for c in server.store.list_conversations(a.dataset)]
        cl = a.checklist or server.store.default_checklist()["id"]
        cost = 0.0
        for n, cid in enumerate(ids, 1):
            try:
                v = server.run_evaluation(cid, cl, a.mode)
                cost += v.get("cost_usd") or 0
                flag = " ГРУБАЯ ОШИБКА" if v["final"]["gross_error"] else ""
                print(f"[{n}/{len(ids)}] {cid}: {v['final']['total']} ({v['engine']}){flag}")
            except server.ApiError as ex:
                print(f"[{n}/{len(ids)}] {cid}: ОШИБКА {ex.payload}", file=sys.stderr)
        print(f"Готово. Стоимость LLM: ${cost:.4f} (≈ ${cost / max(len(ids), 1):.4f} за оценку)")
    elif a.cmd == "compare":
        compare(a)
    elif a.cmd == "report":
        for c in server.store.list_conversations(a.dataset):
            le = c["latest_evaluation"] or {}
            print(f"{c['conversation_id']:<20} {c['language']:<3} {c['channel']:<11} "
                  f"{le.get('total', '—')!s:<8} {'ГРУБАЯ' if le.get('gross_error') else ''}")


EXPORT_CODES = {"01": "contact", "02": "discovery", "03": "identification", "04": "consultation",
                "05": "empathy", "06": "dialogue", "07": "closure", "08": "critical"}
EXPORT_ORDER = list(EXPORT_CODES.values())


def _export_value(crit, answer):
    if answer in (None, "na"):
        return None
    if crit["type"] == "scale":
        v = float(answer)
        return int(v) if v.is_integer() else v
    return answer == "yes"


def _export_one(cid):
    ev = None
    try:
        ev = server.store.latest_evaluation(cid, EXPORT_ARGS.checklist)
        if not ev:
            raise ValueError("Диалог не оценён.")
        crits = ev["checklist_snapshot"]["criteria"]
        results = {r["criterion_id"]: r for r in (ev.get("final_results") or ev["results"])}
        out = {}
        for pos, c in enumerate(crits):
            code = EXPORT_CODES.get(str(c.get("code", "")).zfill(2)) or \
                (EXPORT_ORDER[pos] if pos < len(EXPORT_ORDER) else None)
            if not code or code in out:
                continue
            r = results.get(c["id"])
            if r is None:
                raise ValueError(f"Нет результата по критерию {c['id']}.")
            turns = sorted({int(e["index"]) + 1 for e in (r.get("evidence") or [])
                            if isinstance(e.get("index"), int)})
            out[code] = {"criterion_id": code, "value": _export_value(c, r.get("answer")),
                         "rationale": (r.get("explanation") or r.get("na_reason") or "").strip(),
                         "evidence_turns": turns}
        missing = [k for k in EXPORT_ORDER if k not in out]
        if missing:
            raise ValueError("В чек-листе нет критериев: " + ", ".join(missing))
        sc = ev.get("final_score") or ev["score"]
        if sc.get("total") is None:
            raise ValueError("Итог не рассчитан.")
        return {"conversation_id": cid, "status": "ok", "criteria": [out[k] for k in EXPORT_ORDER],
                "score": {"final_score": round(float(sc["total"]), 2),
                          "critical_flag": bool(out["critical"]["value"])}}, ev
    except Exception as e:  # noqa: BLE001 — по требованию организаторов ошибка сохраняется записью
        return {"conversation_id": cid, "status": "error", "criteria": [], "score": None,
                "error": str(e) or e.__class__.__name__}, ev


EXPORT_ARGS = None


def export(a):
    global EXPORT_ARGS
    EXPORT_ARGS = a
    convs = server.store.list_conversations(a.dataset)
    if not convs:
        sys.exit(f"Набор {a.dataset!r} пуст или не найден. Сначала: python3 cli.py fetch <group_id>")
    rows, engines, seen = [], set(), set()
    for c in convs:
        cid = c["conversation_id"]
        if cid in seen:
            continue
        seen.add(cid)
        row, ev = _export_one(cid)
        rows.append(row)
        if ev and row["status"] == "ok":
            engines.add(ev.get("engine") or "")
    llm = sorted(e.split(":", 1)[1] for e in engines if e.startswith("llm:"))
    has_heur = any(not e.startswith("llm:") for e in engines)
    name = a.model_name or ", ".join(llm + (["offline heuristic rules"] if has_heur else [])) or "unknown"
    mode = "hybrid" if (llm and has_heur) else "external_api" if llm else "local"
    doc = {"schema_version": "1.0", "team_name": a.team, "model": {"mode": mode, "name": name},
           "results": rows}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    errs = [r for r in rows if r["status"] == "error"]
    print(f"Сохранено: {a.out} — записей {len(rows)}, ok {len(rows) - len(errs)}, ошибок {len(errs)}; "
          f"модель: {mode} / {name}")
    for r in errs:
        print(f"  ОШИБКА {r['conversation_id']}: {r['error']}")
    if engines - {e for e in engines if e.startswith("llm:")}:
        print("  ВНИМАНИЕ: часть оценок сделана офлайн-правилами (heuristic). Переоцените их в режиме llm.")


def compare(a):
    import csv
    from backend import scoring

    with open(a.gold, encoding="utf-8-sig") as fh:
        gold_rows = list(csv.DictReader(fh))
    crit_cols = [c for c in gold_rows[0].keys() if c not in ("conversation_id", "disputed", "notes")]
    per_crit = {c: [0, 0] for c in crit_cols}          # совпало, всего
    disputed_hits = 0
    abs_err, n_tot = [], 0
    gross = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    mismatches, missing = [], []

    for g in gold_rows:
        cid = g["conversation_id"]
        ev = server.store.latest_evaluation(cid, a.checklist)
        if not ev:
            missing.append(cid)
            continue
        cl = ev["checklist_snapshot"]
        by_id = {c["id"]: c for c in cl["criteria"]}
        model = {r["criterion_id"]: r for r in ev["results"]}
        gold_ans = {}
        for col in crit_cols:
            if col not in by_id or col not in model:
                continue
            ga, _ = scoring.normalize_answer(by_id[col], g[col])
            gold_ans[col] = ga
            ma = model[col]["answer"]
            per_crit[col][1] += 1
            if ga == ma:
                per_crit[col][0] += 1
            else:
                is_disp = col in (g.get("disputed") or "").split(";")
                disputed_hits += is_disp
                mismatches.append({"conversation_id": cid, "criterion": col, "gold": ga, "model": ma,
                                   "disputed": "да" if is_disp else "",
                                   "explanation": model[col].get("explanation", ""), "gold_note": g.get("notes", "")})
        gt = scoring.compute(cl, gold_ans)["total"]
        mt = ev["score"]["total"]
        if gt is not None and mt is not None:
            abs_err.append(abs(gt - mt))
        n_tot += 1
        gflag = next((c["id"] for c in cl["criteria"] if c["type"] == "flag"), None)
        if gflag and gflag in gold_ans:
            gy, my = gold_ans[gflag] == "yes", model[gflag]["answer"] == "yes"
            gross["tp" if gy and my else "fn" if gy else "fp" if my else "tn"] += 1

    print(f"Сравнено диалогов: {n_tot}" + (f"  (нет оценки: {len(missing)})" if missing else ""))
    print("\nСовпадение по критериям:")
    tm, tt = 0, 0
    for col, (m, t) in per_crit.items():
        if t:
            tm, tt = tm + m, tt + t
            print(f"  {col}: {m}/{t} = {100 * m / t:.1f}%")
    if tt:
        print(f"  ВСЕГО: {tm}/{tt} = {100 * tm / tt:.1f}%")
    if abs_err:
        print(f"\nСредняя ошибка итога (MAE): {sum(abs_err) / len(abs_err):.2f} балла; "
              f"итог в пределах ±5: {sum(e <= 5 for e in abs_err)}/{len(abs_err)}")
    print(f"Грубые ошибки: найдено {gross['tp']} из {gross['tp'] + gross['fn']}, "
          f"ложных срабатываний {gross['fp']}")
    print(f"Расхождений: {len(mismatches)}, из них в спорных местах разметки: {disputed_hits}")
    if a.details:
        print()
        for m in mismatches:
            print(f"- {m['conversation_id']} {m['criterion']}: эталон={m['gold']} модель={m['model']}"
                  f"{' (спорно)' if m['disputed'] else ''} | {m['explanation'][:150]}")
    if a.out:
        with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(mismatches[0].keys()) if mismatches else ["conversation_id"])
            w.writeheader()
            w.writerows(mismatches)
        print(f"Расхождения сохранены: {a.out}")


if __name__ == "__main__":
    main()
