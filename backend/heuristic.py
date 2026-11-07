"""Офлайн-оценщик на правилах (RU/KZ/EN).

Нужен, чтобы система работала без ключа LLM и как страховка, если модель вернула
неполный ответ. Точность ниже, чем у LLM, — уверенность (confidence) ставится низкая.
"""
from __future__ import annotations

import re

from .transcript import WAIT_WORDS, fmt_dur

GREET = {
    "RU": ["здравствуй", "добрый день", "добрый вечер", "доброе утро", "доброго дня", "приветству", "привет"],
    "KZ": ["сәлеметсіз", "сәлем", "қайырлы күн", "қайырлы таң", "қайырлы кеш", "армысыз", "салеметсиз", "саламатсыз"],
    "EN": ["hello", "hi ", "hi,", "hi!", "good morning", "good afternoon", "good evening", "greetings", "hey"],
}
INTRO_CS = [
    r"(?:^|[\s,.!])[Яя]\s+[А-ЯЁ][а-яё]+", r"[Мм]ен\s+[А-ЯӘҒҚҢӨҰҮҺІ][\wәғқңөұүһі]+",
    r"[А-ЯӘҒҚҢӨҰҮҺІ][\wәғқңөұүһі]+(?:мын|мін|пын|пін)\b", r"I'm\s+[A-Z][a-z]+", r"I am\s+[A-Z][a-z]+",
]
INTRO = [
    r"меня зовут", r"с вами (?:на связи )?\w+", r"на связи\s+\w+", r"это\s+[А-ЯЁ]\w+", r"оператор\s+[А-ЯЁ]\w+",
    r"менің атым", r"атым\s+\w+", r"мен\s+[А-ЯӘҒҚҢӨҰҮҺІ]\w+", r"сізбен\s+\w+\s+байланыста", r"операторы?\s+\w+",
    r"my name is", r"i am \w+", r"i'm \w+", r"this is \w+", r"you(?:'re| are) chatting with",
]
QUESTION_HINTS = ["уточните", "подскажите", "какой", "какая", "какие", "когда", "правильно понимаю",
                  "нақтылаңыз", "айтыңызшы", "қандай", "қашан", "could you", "can you tell", "which",
                  "what is your", "please specify", "please confirm"]
PROTECTED = ["баланс", "номер счёта", "номер счета", "мой счёт", "мой счет", "моём счёте", "моем счете",
             "моего счёта", "моего счета", "на счёте", "на счете", "со счёта", "со счета", "к счёту", "к счету",
             "пароль", "вывод", "вывести", "перевести деньги", "снять", "выписк", "мой договор",
             "мой портфель", "моих сделок", "мои сделки", "заблокир", "номер телефона", "смен", "персональн", "мои данные", "ордер",
             "шоттан", "шотымда", "шотымды", "шотыма", "құпия сөз", "ақша шығар", "аудар", "бұғат",
             "my account", "account number", "balance", "password", "withdraw", "transfer", "statement",
             "my portfolio", "my order",
             "blocked", "change my", "personal data"]
VERIFY = ["иин", "кодов", "дата рождения", "даты рождения", "смс-код", "sms", "код из", "верифиц", "идентифиц",
          "подтвердите личность", "паспорт", "фио", "жсн", "туған күн", "кодтық сөз", "жеке басы",
          "verify", "verified", "verification", "identity", "date of birth", "security question", "code word",
          "identified", "личность подтвержд", "подтверждена"]
COMPLAINT = ["недовол", "ужас", "безобраз", "долго", "проблем", "не работает", "жалоб", "возмущ", "не могу", "ошибк",
             "наразы", "мәселе", "жұмыс істемейді", "шағым", "ұзақ", "қате", "алмай",
             "frustrat", "terrible", "problem", "not working", "complain", "annoy", "can't", "cannot", "error", "issue",
             "disappoint", "angry", "unacceptable"]
EMPATHY = ["извин", "сожале", "понима", "неудобств", "сочувств", "к сожалению", "благодарю за терпение",
           "кешіріңіз", "кешірім", "түсінемін", "өкінішке", "қолайсыздық",
           "sorry", "apolog", "understand", "inconvenience", "unfortunately", "thank you for your patience"]
RUDE = ["читать умеете", "читать не умеете", "дура", "идиот", "тупой", "тупая", "заткн", "отстань", "бестолк", "ақымақ", "жынды", "idiot", "stupid",
        "shut up", "dumb", "moron"]
BYPASS = ["скиньте деньги", "мне на карту", "лично предлагаю", "через компанию оформлять не надо", "личный номер",
          "частная консультация", "за плату", "ақылы", "жеке нөмір", "personal number", "private advice",
          "i charge", "переведите мне", "на мою карту", "мою личную карту", "лично мне", "мой личный номер", "мой номер",
          "ваш личный номер", "в частном порядке", "частн", "помимо компании", "мимо компании",
          "менің картама", "маған аударыңыз", "жеке нөмір", "жеке түрде",
          "transfer to me", "my personal", "my card", "privately", "outside the company", "your personal number",
          "whatsapp me", "send me the money"]
CONFIDENTIAL = ["другого клиента", "другой клиент", "пароль от", "внутренн", "басқа клиент", "another client",
                "other client's", "internal system password"]
REASK = ["я спрашиваю", "в каком меню", "какое приложение", "i'm asking", "how do you know", "не понял", "не поняла", "что вы имеете", "в смысле", "не понятно", "непонятно", "повторите", "так что",
         "түсінбедім", "түсініксіз", "не дегеніңіз", "what do you mean", "i don't understand", "not clear",
         "confused", "sorry?", "pardon"]
FAREWELL = ["до свидания", "всего доброго", "хорошего дня", "хорошего вечера", "всего хорошего", "до встречи",
            "сау болыңыз", "күніңіз сәтті", "сәттілік", "қош", "жақсы күн",
            "goodbye", "bye", "have a nice", "have a great", "have a good", "take care"]
MORE_HELP = ["чем-то ещё", "чем-нибудь ещё", "ещё вопрос", "другие вопросы", "чем еще", "чем ещё могу",
             "тағы сұрақ", "басқа сұрақ", "тағы көмек", "anything else", "other questions", "further help",
             "anything more"]
ABRUPT = ["соединение с клиентом прервано", "байланыс үзілді", "connection to customer lost",
          "клиент завершил разговор", "клиент покинул чат", "клиент покинул", "клиент вышел", "клиент закрыл", "соединение прервано", "связь прервалась",
          "client left", "customer left", "disconnected", "call dropped", "клиент отключ"]
SUBSTANCE_MIN_WORDS = 12
GENERIC_HELP = ["чем могу помочь", "с чем помочь", "чем помочь", "how can i help", "how may i help",
                "қалай көмектесе", "не көмек", "где именно ищете", "қай сайтқа"]
ALREADY_SAID = ["уже писал", "уже писала", "писал выше", "писала выше", "я же написал", "жоғарыда жаздым",
                "жаздым ғой", "i already", "as i said", "i wrote above"]
VERIFIED_EVENT = ["личность клиента подтверждена", "жеке басы расталды", "identity verified",
                  "идентификац", "verified"]
VERIFIED_BY_OP = ["идентификацию успешно", "идентификация пройдена", "личность подтверждена",
                  "identity is verified", "растау сәтті"]
ACCOUNT_DISCLOSURE = ["на вашем счёте", "на вашем счете", "вашем счёте есть", "ваш баланс", "по вашему счёту",
                      "шотыңызда", "шотыңыздағы", "on your account", "your balance", "your account has",
                      "вижу ограничение", "көріп тұрмын"]
NO_ANSWER = ["тогда не знаю", "не знаю", "всё есть в приложении", "все есть в приложении", "ничего не сделать",
             "білмеймін", "i don't know", "no idea"]
RESOLVED = ["спасибо", "понятно", "нашла", "нашёл", "нашел", "вижу", "получилось", "теперь понятно", "скачал",
            "рақмет", "рахмет", "таптым", "түсінікті", "түсіндім", "көрдім", "ашылды", "дайын",
            "thank", "got it", "found it", "that worked", "understood", "that's all", "great"]


def _has(text, words):
    low = text.lower()
    return next((w for w in words if w in low), None)


def _ev(m, max_len=140):
    q = m["text"].strip()
    return {"index": m["index"], "quote": q if len(q) <= max_len else q[:max_len] + "…"}


def _res(cid, answer, explanation, evidence=None, checked=None, na_reason=None, confidence=0.45):
    return {"criterion_id": cid, "answer": answer, "explanation": explanation,
            "evidence": evidence or [], "checked_range": checked, "na_reason": na_reason,
            "confidence": confidence}


def _rng(msgs):
    return {"from": msgs[0]["index"], "to": msgs[-1]["index"]} if msgs else None


def evaluate_rule(criterion: dict, msgs: list[dict], language: str, facts: dict) -> dict:
    cid = criterion["id"]
    rule = criterion.get("rule") or ""
    ops = [m for m in msgs if m["speaker"] == "operator"]
    clients = [m for m in msgs if m["speaker"] == "client"]
    lang = (language or "RU").upper()

    if rule == "greeting":
        if not ops:
            return _res(cid, "no", "Оператор не написал ни одной реплики.", checked=_rng(msgs))
        first = ops[0]
        greet = _has(first["text"], GREET.get(lang, []))
        other = next((l for l, ws in GREET.items() if l != lang and _has(first["text"], ws)), None)
        intro = any(re.search(p, first["text"], re.I) for p in INTRO) or \
            any(re.search(p, first["text"]) for p in INTRO_CS)
        if greet and intro:
            return _res(cid, "yes", f"В первом ответе оператор поздоровался на языке клиента ({lang}) и представился.",
                        [_ev(first)], confidence=0.6)
        why = []
        if not greet:
            why.append("нет приветствия на языке клиента" + (f" (приветствие на {other})" if other else ""))
        if not intro:
            why.append("оператор не представился")
        return _res(cid, "no", "Первый ответ оператора: " + "; ".join(why) + ".", [_ev(first)],
                    checked={"from": first["index"], "to": first["index"]})

    if rule == "needs":
        if not clients or sum(len(m["text"].split()) for m in clients) < 4:
            return _res(cid, "na", "Клиент не сформулировал запрос — выявлять потребность было не в чем.",
                        [_ev(clients[0])] if clients else [],
                        na_reason="Клиент не сформулировал запрос.")
        first_op = ops[0] if ops else None
        before = [m for m in clients if first_op and m["index"] < first_op["index"]]
        known = sum(len(m["text"].split()) for m in before) >= 6
        generic = first_op and _has(first_op["text"], GENERIC_HELP)
        repeat = next((m for m in clients if first_op and m["index"] > first_op["index"]
                       and _has(m["text"], ALREADY_SAID)), None)
        if (generic and known) or repeat:
            ev = [_ev(first_op)] + ([_ev(repeat)] if repeat else [])
            return _res(cid, "no", "Оператор переспросил то, что клиент уже описал до подключения оператора.", ev,
                        confidence=0.55)
        q = [m for m in ops[:-1] if "?" in m["text"] or _has(m["text"], QUESTION_HINTS)]
        if q and not _has(q[0]["text"], GENERIC_HELP):
            return _res(cid, "yes", "Оператор уточнил недостающие детали до ответа по существу.", [_ev(q[0])])
        return _res(cid, "na", "Запрос клиента был понятен из его реплик, уточнения не требовались.",
                    [_ev(before[-1] if before else clients[0])],
                    na_reason="Данных для ответа хватало с самого начала.", confidence=0.4)

    if rule == "identification":
        ver = next((m for m in msgs if m["speaker"] == "system" and _has(m["text"], VERIFIED_EVENT)), None) or \
            next((m for m in ops if _has(m["text"], VERIFIED_BY_OP)), None)
        disc = next((m for m in ops if _has(m["text"], ACCOUNT_DISCLOSURE)), None)
        if disc and (not ver or ver["index"] > disc["index"]):
            return _res(cid, "no", "Оператор сообщил сведения о счёте клиента без подтверждённой идентификации.",
                        [_ev(disc)], checked={"from": ops[0]["index"], "to": disc["index"]}, confidence=0.6)
        if ver:
            return _res(cid, "yes", "Личность клиента подтверждена до работы с данными счёта.", [_ev(ver)], confidence=0.6)
        return _res(cid, "na", "Сведения о счёте не раскрывались и защищённых действий не выполнялось.",
                    na_reason="Запрос не требовал идентификации.", confidence=0.45)

    if rule == "consultation":
        if not clients or sum(len(m["text"].split()) for m in clients) < 4:
            return _res(cid, "na", "Клиент не успел сформулировать запрос.",
                        na_reason="Чат закончился до того, как клиент сформулировал запрос.")
        main = max(ops, key=lambda m: len(m["text"]), default=None)
        if not ops or sum(len(m["text"].split()) for m in ops) < 6 or any(_has(m["text"], NO_ANSWER) for m in ops):
            bad_m = next((m for m in ops if _has(m["text"], NO_ANSWER)), main)
            return _res(cid, 0, "Ответа по существу нет.", [_ev(bad_m)] if bad_m else [], checked=_rng(msgs))
        after_op = [m for m in clients if m["index"] > ops[0]["index"]]
        resolved = next((m for m in reversed(after_op) if _has(m["text"], RESOLVED)), None)
        last_client = after_op[-1] if after_op else None
        open_q = last_client and "?" in last_client["text"] and not any(m["index"] > last_client["index"] for m in ops[:-1]) \
            and ops[-1]["index"] > last_client["index"] and not _has(ops[-1]["text"], QUESTION_HINTS) \
            and len(ops[-1]["text"].split()) < 8
        reasks = [m for m in after_op if _has(m["text"], REASK + ALREADY_SAID)]
        if open_q:
            return _res(cid, 10, "Последний вопрос клиента остался без ответа по существу.", [_ev(last_client)],
                        checked={"from": last_client["index"], "to": msgs[-1]["index"]}, confidence=0.35)
        if resolved and not reasks:
            return _res(cid, 20, "Клиент подтвердил, что вопрос решён.", [_ev(resolved)], confidence=0.4)
        if resolved:
            return _res(cid, 15, "Вопрос решён, но не с первого ответа.", [_ev(resolved)], confidence=0.35)
        return _res(cid, 15, "Дан ответ; явного подтверждения от клиента нет.", [_ev(main)], confidence=0.3)

    if rule == "empathy":
        rude = next((m for m in ops if _has(m["text"], RUDE)), None)
        if rude:
            return _res(cid, "no", "Оператор допустил невежливую реплику.", [_ev(rude)], confidence=0.6)
        comp = next((m for m in clients if _has(m["text"], COMPLAINT)), None)
        if comp:
            emp = next((m for m in ops if m["index"] > comp["index"] and _has(m["text"], EMPATHY)), None)
            if emp:
                return _res(cid, "yes", "Клиент описал проблему, оператор отреагировал на неё.", [_ev(comp), _ev(emp)])
            return _res(cid, "no", "Клиент выразил недовольство или описал неудобство, оператор не отреагировал на это.",
                        [_ev(comp)], checked={"from": comp["index"], "to": msgs[-1]["index"]})
        return _res(cid, "yes", "Оператор вежлив; недовольства клиент не выражал.", [_ev(ops[0])] if ops else [])

    if rule == "dialog":
        flaws, ev = [], []
        fr = facts.get("first_response")
        if fr and fr["exceeds"]:
            flaws.append(f"первая реакция {fmt_dur(fr['seconds'])} (порог {fmt_dur(facts['threshold_sec'])})")  # только если порог включён
            ev.append(_ev(msgs[fr["operator_index"]]))
        for g in facts.get("long_gaps", []):
            if not g["operator_warned"] and not (fr and g["to_index"] == fr["operator_index"]):
                flaws.append(f"ожидание {fmt_dur(g['seconds'])} без предупреждения")
                ev.append(_ev(msgs[g["to_index"]]))
        reask = [m for m in clients if _has(m["text"], REASK + ALREADY_SAID)]
        if reask:
            ev.append(_ev(reask[0]))
            v = 4 if len(reask) == 1 else 0
            txt = "Клиенту пришлось переспрашивать" + (f"; также: {', '.join(flaws)}" if flaws else "") + "."
            return _res(cid, v, txt, ev, confidence=0.4)
        if len(flaws) >= 2:
            return _res(cid, 4, "Несколько сбоев: " + ", ".join(flaws) + ".", ev)
        if flaws:
            return _res(cid, 7, "Один заметный сбой: " + flaws[0] + ".", ev)
        return _res(cid, 10, "Ответы последовательные; долгих ожиданий без предупреждения нет.",
                    [_ev(ops[0])] if ops else [], confidence=0.4)

    if rule == "closing":
        tail = msgs[-4:]
        abrupt = next((m for m in tail if m["speaker"] in ("system", "client") and _has(m["text"], ABRUPT)), None)
        last_op = ops[-1] if ops else None
        bye = next((m for m in reversed(ops[-3:]) if _has(m["text"], FAREWELL)), None)
        more = next((m for m in reversed(ops[-3:]) if _has(m["text"], MORE_HELP)), None)
        if bye:
            ev = [_ev(more)] if more and more is not bye else []
            return _res(cid, "yes", "Оператор " + ("предложил дальнейшую помощь и " if more else "") + "попрощался.",
                        ev + [_ev(bye)], confidence=0.6)
        if abrupt:
            return _res(cid, "na", "Чат оборвался до завершения.", [_ev(abrupt)],
                        na_reason="Чат оборвался до возможности его завершить.")
        if msgs and msgs[-1]["speaker"] == "client" and last_op and msgs[-1]["index"] > last_op["index"] + 1:
            return _res(cid, "na", "Последние реплики — клиента, оператор не успел ответить.",
                        [_ev(msgs[-1])], na_reason="Чат оборвался до возможности его завершить.", confidence=0.35)
        return _res(cid, "no", "Оператор не попрощался и не подвёл итог в конце диалога.",
                    [_ev(last_op)] if last_op else [], checked=_rng(msgs[-4:]))

    if rule == "gross":
        ver = next((m for m in msgs if m["speaker"] == "system" and _has(m["text"], VERIFIED_EVENT)), None)
        disc = next((m for m in ops if _has(m["text"], ACCOUNT_DISCLOSURE)), None)
        for words, label in ((RUDE, "оскорбление клиента"), (BYPASS, "предложение услуги в обход компании"),
                             (CONFIDENTIAL, "раскрытие конфиденциальной информации")):
            hit = next((m for m in ops if _has(m["text"], words)), None)
            if hit:
                return _res(cid, "yes", f"Выявлено: {label}.", [_ev(hit)], confidence=0.55)
        if disc and (not ver or ver["index"] > disc["index"]):
            return _res(cid, "yes", "Выявлено: раскрытие сведений о счёте без подтверждения личности.",
                        [_ev(disc)], confidence=0.5)
        return _res(cid, "no", "Оскорблений, предложений в обход компании и раскрытия конфиденциальных данных не выявлено.",
                    checked=_rng(ops), confidence=0.5)

    # Пользовательский критерий: ключевые слова в репликах оператора
    kws = [k.lower() for k in criterion.get("keywords") or [] if k.strip()]
    if kws:
        hit = next((m for m in ops if _has(m["text"], kws)), None)
        if criterion["type"] == "scale":
            steps = sorted({s["value"] for s in criterion.get("scale", [])})
            return _res(cid, steps[-1] if hit else steps[0],
                        "Найдено ключевое слово в репликах оператора." if hit else "Ключевые слова не найдены.",
                        [_ev(hit)] if hit else [], checked=None if hit else _rng(ops), confidence=0.35)
        return _res(cid, "yes" if hit else "no",
                    "Найдено ключевое слово в репликах оператора." if hit else "Ключевые слова в репликах оператора не найдены.",
                    [_ev(hit)] if hit else [], checked=None if hit else _rng(ops), confidence=0.35)
    if criterion.get("na_allowed"):
        return _res(cid, "na", "Офлайн-режим не умеет оценивать этот критерий без ключевых слов. Подключите LLM.",
                    na_reason="Нет правила для офлайн-оценки.", confidence=0.1)
    steps = sorted({s["value"] for s in criterion.get("scale", [])}) if criterion["type"] == "scale" else None
    return _res(cid, steps[0] if steps else "no",
                "Офлайн-режим не умеет оценивать этот критерий без ключевых слов. Подключите LLM.",
                checked=_rng(ops), confidence=0.1)
