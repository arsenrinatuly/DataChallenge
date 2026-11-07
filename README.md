# CQA — Conversation Quality Analytics

Прототип для хакатона Freedom Broker. Система оценивает работу оператора в чатах и звонках по настраиваемому чек-листу, показывает обоснования со ссылками на реплики и поддерживает апелляции.

## Быстрый старт

Нужен только **Python 3.10+**. Внешних зависимостей нет.

```bash
python3 server.py                 # открыть http://127.0.0.1:8000 — интерфейс + API
python3 server.py --seed-demo     # то же + 8 демо-диалогов
```

Фронтенд лежит в `web/` (описание в `web/FRONTEND_README.md`). Сервер раздаёт его сам, проблем с CORS нет.

Загрузка набора организаторов:

```bash
python cli.py fetch DEV           # или кнопка «Загрузить набор» в интерфейсе (POST /api/datasets/fetch)
python cli.py evaluate --dataset DEV
python cli.py report --dataset DEV
```

Если API организаторов недоступен, скачайте JSON по ссылке из задания и импортируйте его: `python cli.py import dev.json`.

### Подключение LLM

Скопируйте `.env.example` в `.env` и выберите провайдера:

| Вариант | Переменные |
|---|---|
| Anthropic Claude | `CQA_LLM_PROVIDER=anthropic`, `CQA_LLM_API_KEY`, `CQA_LLM_MODEL` |
| OpenAI / Gemini / Groq / OpenRouter | `CQA_LLM_PROVIDER=openai`, `CQA_LLM_API_KEY`, `CQA_LLM_MODEL`, `CQA_LLM_BASE_URL` |
| Локально (Ollama) | `CQA_LLM_PROVIDER=openai`, `CQA_LLM_BASE_URL=http://localhost:11434/v1`, `CQA_LLM_MODEL=qwen2.5:14b` |

Без ключа система работает в **офлайн-режиме**: оценка идёт по правилам на ключевых словах RU/KZ/EN. Точность у этого режима ниже, он нужен как запасной.

**Стоимость одной оценки.** Чтобы её считать, задайте цены `CQA_PRICE_IN_PER_M` и `CQA_PRICE_OUT_PER_M` (USD за 1M токенов) с прайс-страницы провайдера. Одна оценка — это один вызов модели, повторный вызов бывает только при невалидном JSON. Стоимость возвращается в поле `cost_usd` каждой оценки. Команда `cli.py evaluate` печатает среднюю стоимость по набору.

## Как устроена оценка

1. Транскрипт нормализуется: роли, метки времени `MM:SS` или ISO 8601, смещения от начала для перемотки аудио.
2. Код **вычисляет факты о времени** от передачи диалога оператору: первую реакцию и паузы без предупреждения. Сам порог первой реакции (3 минуты) по PDF в оценку не входит; при необходимости он включается полем `first_response_threshold_sec` в чек-листе.
3. **LLM** получает пронумерованные реплики и чек-лист. По каждому критерию она возвращает:
   - ответ (только из допустимых значений);
   - объяснение;
   - реплики-доказательства;
   - проверенный участок (если действие пропущено);
   - причину N/A.
4. Ответ модели **валидируется**:
   - N/A там, где он запрещён, заменяется на минимальную оценку;
   - значения шкалы приводятся к ближайшей ступени;
   - индексы реплик проверяются;
   - цитаты сверяются с текстом.

   Если модель пропустила критерий, его оценивают правила.
5. **Итог считает код, а не модель** (`backend/scoring.py`), строго по PDF:
   - шкала переводится в баллы пропорционально весу;
   - вес критериев с N/A перераспределяется, максимум остаётся 100;
   - итог округляется до двух знаков;
   - флаг грубой ошибки ставится отдельно.

Пример из тестов: 03 = N/A, 04 = 15 из 20, 06 = 7 из 10, 07 = «Нет». Получается 65,5 / 80 · 100 = **81,88**.

## Проверка качества оценки

`data/gold_dev.csv` содержит ручную разметку 60 чатов DEV по 8 критериям. Колонка `disputed` отмечает спорные места, `notes` — пояснения. Звонки не размечены: это шумная расшифровка речи, эталон по ним был бы ненадёжным.

```bash
python cli.py evaluate --dataset DEV          # оценить (LLM, если настроен)
python cli.py compare                         # совпадение по критериям, MAE итога, грубые ошибки
python cli.py compare --details --out diff.csv
```

Офлайн-режим на DEV: совпадение 89,4%, MAE итога 8,06, грубые ошибки найдены 8 из 8. **Эти цифры завышены:** правила настраивались на этих же диалогах. Честную оценку даст контрольный набор.

## Чек-листы и версии

Каждое сохранение чек-листа создаёт **новую версию** (`cl_xxx@2`). Старые оценки хранят снимок чек-листа, на котором были сделаны, поэтому замена критерия на защите ничего не ломает: сохраняем новую версию и запускаем пакетную оценку.

Свой критерий оценивает LLM по его формулировке. В офлайн-режиме у критерия можно задать `keywords`.

## Апелляции

`POST /api/appeals` создаёт апелляцию, а `POST /api/appeals/{id}/decision` выносит решение (`confirm` или `change` с причиной). После решения итог пересчитывается. В оценке хранятся исходные результаты (`original`) и финальные (`final`), а у критерия — решение проверяющего.

## API

```
GET  /api/health
POST /api/datasets/fetch             { group_id }
POST /api/conversations/import       JSON из API организаторов
GET  /api/conversations[?dataset=]
GET  /api/conversations/{id}
GET  /api/checklists | GET/PUT/DELETE /api/checklists/{id} | POST /api/checklists
POST /api/checklists/{id}/default
POST /api/evaluate                   { conversation_id, checklist_id?, mode? auto|llm|heuristic }
POST /api/evaluate/batch             { checklist_id?, dataset? | conversation_ids?, mode? }
GET  /api/jobs/{job_id}
GET  /api/evaluations/{id}
POST /api/appeals                    { evaluation_id, criterion_id, comment, author? }
GET  /api/appeals[?status=open|decided]
GET  /api/appeals/{id}
POST /api/appeals/{id}/decision      { action: confirm|change, new_answer?, reason, reviewer? }
```

Формат объекта `Evaluation` описан в ТЗ фронтенда. Фронтенд кладётся в папку `web/`, сервер раздаёт его сам, поэтому проблем с CORS нет.

## Структура

```
server.py            HTTP-сервер и маршруты API
cli.py               консольные команды (fetch / import / evaluate / report)
backend/scoring.py   расчёт баллов, N/A, секции, валидация чек-листа
backend/evaluator.py промпт, валидация ответа LLM, апелляции, формат для UI
backend/llm.py       клиенты Anthropic и OpenAI-совместимых API (urllib)
backend/heuristic.py офлайн-оценка по правилам RU/KZ/EN
backend/transcript.py нормализация транскрипта, паузы и первая реакция
backend/storage.py   SQLite (data/cqa.sqlite3)
data/                чек-лист по умолчанию и демо-набор
tests/               python -m unittest discover tests
web/                 фронтенд
```
