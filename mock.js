const clone = value => structuredClone(value);
const now = () => Math.floor(Date.now() / 1000);

export const starterChecklist = {
  id: 'cl_chat@1', version: 1, name: 'Чек-лист качества чатов', rounding: 2, is_default: true,
  sections: [
    { id: 'start', title: 'Начало и понимание запроса' },
    { id: 'safety', title: 'Безопасность и решение' },
    { id: 'flow', title: 'Ведение и завершение диалога' },
    { id: 'gross', title: 'Грубые нарушения' }
  ],
  criteria: [
    { id: 'c01', code: '01', section: 'start', title: 'Установление контакта', type: 'binary', weight: 10, na_allowed: false, yes_rule: 'Оператор поздоровался на языке клиента и представился в первом ответе.', na_rule: '', scale: [], keywords: ['здравствуйте', 'добрый день'] },
    { id: 'c02', code: '02', section: 'start', title: 'Выявление потребности', type: 'binary', weight: 15, na_allowed: true, yes_rule: 'Учёл известные детали и уточнил недостающее до ответа.', na_rule: 'Данных для ответа хватало с самого начала.', scale: [], keywords: ['уточните', 'подскажите'] },
    { id: 'c03', code: '03', section: 'safety', title: 'Идентификация', type: 'binary', weight: 20, na_allowed: true, yes_rule: 'Проверка личности подтверждена до раскрытия данных или защищённого действия.', na_rule: 'Запрос не требовал идентификации.', scale: [], keywords: ['удостоверение', 'проверка'] },
    { id: 'c04', code: '04', section: 'safety', title: 'Корректная и полная консультация', type: 'scale', weight: 20, na_allowed: true, yes_rule: 'Оцените правильность и полноту ответа или следующего шага.', na_rule: 'Чат закончился до формулировки запроса.', scale: [{ value: 0, label: 'Ответа по существу нет или рекомендация ошибочна' }, { value: 5, label: 'Общая подсказка, но следующий шаг неясен' }, { value: 10, label: 'Часть запроса закрыта' }, { value: 15, label: 'Основной вопрос решён' }, { value: 20, label: 'Все существенные вопросы закрыты' }], keywords: [] },
    { id: 'c05', code: '05', section: 'flow', title: 'Эмпатия и клиентоориентированность', type: 'binary', weight: 15, na_allowed: false, yes_rule: 'Оператор вежлив и отвечает на конкретную проблему клиента.', na_rule: '', scale: [], keywords: ['понимаю', 'помогу'] },
    { id: 'c06', code: '06', section: 'flow', title: 'Управление диалогом, скорость и грамотность', type: 'scale', weight: 15, na_allowed: false, yes_rule: 'Оцените ясность, порядок ответов и предупреждение об ожидании. Порог первой реакции не входит в исходную оценку.', na_rule: '', scale: [{ value: 0, label: 'Диалог непонятен' }, { value: 4, label: 'Клиенту приходится переспрашивать' }, { value: 7, label: 'Один заметный сбой' }, { value: 10, label: 'Ясные и связные ответы' }], keywords: [] },
    { id: 'c07', code: '07', section: 'flow', title: 'Завершение', type: 'binary', weight: 5, na_allowed: true, yes_rule: 'Оператор подвёл итог или предложил помощь и попрощался.', na_rule: 'Чат оборвался до возможности завершить его.', scale: [], keywords: ['до свидания', 'обращайтесь'] },
    { id: 'c08', code: '08', section: 'gross', title: 'Грубые ошибки', type: 'flag', weight: 0, na_allowed: false, yes_rule: 'Отметьте оскорбление, услугу в обход компании или раскрытие конфиденциальной информации.', na_rule: '', scale: [], keywords: [] }
  ]
};

const seedConversations = [
  { conversation_id: 'p1-ru-001', dataset: 'DEV', channel: 'agent chat', language: 'RU', audio_url: null, transcript: [
    { timestamp: '00:02', speaker: 'client', text: 'Здравствуйте! Подскажите, какая комиссия за покупку акций?' },
    { timestamp: '00:18', speaker: 'operator', text: 'Здравствуйте! Меня зовут Алия, помогу разобраться.' },
    { timestamp: '00:25', speaker: 'operator', text: 'Комиссия зависит от вашего тарифного плана. Какой тариф у вас подключён?' },
    { timestamp: '00:41', speaker: 'client', text: 'Я пока только выбираю тариф. Есть вариант для начинающих?' },
    { timestamp: '01:03', speaker: 'operator', text: 'Да. Посмотрите тариф «Стандарт» в приложении: раздел «Профиль» → «Тарифы». Там указаны актуальные комиссии.' },
    { timestamp: '01:20', speaker: 'client', text: 'Спасибо, понятно.' },
    { timestamp: '01:31', speaker: 'operator', text: 'Пожалуйста! Если появятся вопросы, обращайтесь. Хорошего дня!' }
  ] },
  { conversation_id: 'p1-kz-002', dataset: 'DEV', channel: 'agent chat', language: 'KZ', audio_url: null, transcript: [
    { timestamp: '00:01', speaker: 'client', text: 'Сәлеметсіз бе! Қосымшада шот ашу қалай жүреді?' },
    { timestamp: '00:13', speaker: 'bot', text: 'Сізді операторға қосып жатырмыз.' },
    { timestamp: '00:34', speaker: 'operator', text: 'Сәлеметсіз бе! Менің атым Дана. Сізге көмектесемін.' },
    { timestamp: '00:55', speaker: 'operator', text: 'Қосымшадағы «Шот ашу» бөлімін таңдаңыз. Жеке куәлігіңізді дайындаңыз.' },
    { timestamp: '01:10', speaker: 'client', text: 'Рақмет!' }
  ] },
  { conversation_id: 'p1-en-003', dataset: 'DEV', channel: 'agent chat', language: 'EN', audio_url: null, transcript: [
    { timestamp: '00:03', speaker: 'client', text: 'Hi, where can I see my portfolio report?' },
    { timestamp: '00:27', speaker: 'operator', text: 'Hello! I am Daniel. Open Portfolio, then Reports in the app.' },
    { timestamp: '00:48', speaker: 'client', text: 'I cannot find Reports.' },
    { timestamp: '01:20', speaker: 'operator', text: 'Please check the menu in the top right corner.' },
    { timestamp: '01:42', speaker: 'client', text: 'Found it, thanks.' },
    { timestamp: '01:54', speaker: 'operator', text: 'Happy to help. Have a good day!' }
  ] },
  { conversation_id: 'p1-ru-call-004', dataset: 'DEV', channel: 'voice call', language: 'RU', audio_url: null, transcript: [
    { timestamp: '2026-03-01T10:00:05+05:00', offset: 0, speaker: 'client', text: 'Здравствуйте. Я хочу узнать баланс счёта.' },
    { timestamp: '2026-03-01T10:00:12+05:00', offset: 7, speaker: 'operator', text: 'Здравствуйте, я Арман. Перед этим подтвердим вашу личность.' },
    { timestamp: '2026-03-01T10:00:29+05:00', offset: 24, speaker: 'operator', text: 'Назовите, пожалуйста, кодовое слово.' },
    { timestamp: '2026-03-01T10:00:47+05:00', offset: 42, speaker: 'client', text: 'Готово.' },
    { timestamp: '2026-03-01T10:00:56+05:00', offset: 51, speaker: 'operator', text: 'Спасибо. Проверка пройдена, баланс доступен в приложении.' }
  ] }
];

const answerSeeds = {
  'p1-ru-001': { '01': 'yes', '02': 'yes', '03': 'na', '04': 15, '05': 'yes', '06': 7, '07': 'yes', '08': 'no' },
  'p1-kz-002': { '01': 'yes', '02': 'na', '03': 'na', '04': 20, '05': 'yes', '06': 7, '07': 'na', '08': 'no' },
  'p1-en-003': { '01': 'yes', '02': 'no', '03': 'na', '04': 15, '05': 'yes', '06': 4, '07': 'yes', '08': 'no' },
  'p1-ru-call-004': { '01': 'yes', '02': 'yes', '03': 'yes', '04': 10, '05': 'yes', '06': 7, '07': 'no', '08': 'no' }
};

const makeId = prefix => `${prefix}_${Math.random().toString(36).slice(2, 9)}`;
const round = (value, digits = 2) => Number(value.toFixed(digits));

function score(criteria, checklist) {
  const applicable = criteria.filter(c => c.type !== 'flag' && c.final.answer !== 'na' && Number(c.weight) > 0);
  const denominator = applicable.reduce((sum, c) => sum + Number(c.weight), 0);
  criteria.forEach(c => {
    const definition = checklist.criteria.find(item => item.id === c.criterion_id);
    const rawPoints = definition ? pointsFor(definition, c.final.answer) : null;
    c.final.points = rawPoints == null || !denominator ? null : round(rawPoints / denominator * 100);
  });
  const total = denominator ? round(applicable.reduce((sum, c) => sum + c.final.points, 0), checklist.rounding ?? 2) : null;
  const sections = checklist.sections.filter(s => s.id !== 'gross').map(s => {
    const items = applicable.filter(c => c.section === s.id);
    const weight = items.reduce((sum, c) => sum + Number(c.weight), 0);
    const earned = items.reduce((sum, c) => sum + c.final.points, 0);
    const max = denominator ? round(weight / denominator * 100) : 0;
    return { id: s.id, title: s.title, points: round(earned), max, percent: max ? round(earned / max * 100) : null };
  });
  criteria.forEach(c => { c.final.effective_weight = c.type === 'flag' || c.final.answer === 'na' || !denominator ? 0 : round(Number(c.weight) / denominator * 100); c.final.applicable = c.type !== 'flag' && c.final.answer !== 'na'; });
  return { total, gross_error: criteria.some(c => c.type === 'flag' && c.final.answer === 'yes'), sections };
}

function pointsFor(criterion, answer) {
  if (answer === 'na' || criterion.type === 'flag') return null;
  if (criterion.type === 'binary') return answer === 'yes' ? Number(criterion.weight) : 0;
  const max = Math.max(...(criterion.scale || []).map(s => Number(s.value)), 0);
  return max ? round(Number(answer) / max * Number(criterion.weight)) : 0;
}

function evaluate(conversation, checklist) {
  const seed = answerSeeds[conversation.conversation_id] || {};
  const criteria = checklist.criteria.map((c, position) => {
    const raw = seed[c.code];
    const answer = raw !== undefined && (raw !== 'na' || c.na_allowed) ? raw : c.type === 'scale' ? Math.max(...c.scale.map(s => Number(s.value)), 0) : 'yes';
    const operatorIndices = conversation.transcript.map((m, index) => m.speaker === 'operator' ? index : -1).filter(index => index >= 0);
    const evidenceIndex = c.code === '07' ? operatorIndices.at(-1) : c.code === '04' ? (operatorIndices[2] ?? operatorIndices[1] ?? operatorIndices[0]) : ['02', '06'].includes(c.code) ? (operatorIndices[1] ?? operatorIndices[0]) : operatorIndices[0] ?? 0;
    const evidence = answer === 'na' || (c.type === 'flag' && answer === 'no') ? [] : [{ index: evidenceIndex, quote: conversation.transcript[evidenceIndex].text.slice(0, 95) }];
    const explanation = c.type === 'flag' ? (answer === 'yes' ? 'В разговоре выявлено грубое нарушение.' : 'Грубых нарушений в проверенном разговоре не выявлено.') : answer === 'na' ? `Критерий неприменим: ${c.na_rule || 'условие неприменимости выполнено'}` : answer === 'no' || answer === 0 ? 'В проверенном фрагменте требуемое действие не подтверждено.' : 'Оценка основана на приведённой реплике и контексте разговора.';
    return { criterion_id: c.id, code: c.code, title: c.title, section: c.section, type: c.type, weight: Number(c.weight), original: { answer, points: pointsFor(c, answer) }, final: { answer, points: pointsFor(c, answer) }, explanation, evidence, checked_range: { from: 0, to: conversation.transcript.length - 1 }, na_reason: answer === 'na' ? (c.na_rule || 'Условие N/A выполнено.') : null, confidence: 0.84, appeal: null };
  });
  const final = score(criteria, checklist);
  criteria.forEach(c => { c.original.points = c.final.points; });
  return { id: makeId('ev'), conversation_id: conversation.conversation_id, checklist_id: checklist.id, checklist_name: checklist.name, checklist_version: checklist.version, engine: 'demo:mock', created_at: now(), cost_usd: 0, original: clone(final), final, criteria };
}

export class MockApi {
  constructor() {
    try { this.data = JSON.parse(localStorage.getItem('cqa-demo-v1')); } catch { /* reset damaged demo data */ }
    if (!this.data) this.data = { conversations: clone(seedConversations), checklists: [clone(starterChecklist)], evaluations: [], appeals: [], jobs: {} };
    this.save();
  }
  save() { localStorage.setItem('cqa-demo-v1', JSON.stringify(this.data)); }
  async request(method, path, body) {
    const url = new URL(path, location.origin);
    const p = url.pathname.replace(/^\/api/, '');
    const d = this.data;
    if (method === 'GET' && p === '/health') return { llm: { provider: 'demo', model: 'mock', enabled: false } };
    if (method === 'POST' && p === '/datasets/fetch') return { dataset: body.group_id, imported: d.conversations.filter(c => c.dataset === body.group_id).length };
    if (method === 'POST' && p === '/conversations/import') {
      const records = Array.isArray(body) ? body : body.records || body.data?.records || [];
      if (!Array.isArray(records)) throw new Error('Не найден массив records.');
      let imported = 0;
      records.forEach(record => {
        if (!record.conversation_id || !Array.isArray(record.transcript)) return;
        if (!d.conversations.some(c => c.conversation_id === record.conversation_id)) { d.conversations.push({ ...record, dataset: record.dataset || body.data?.dataset_group_id || 'IMPORT' }); imported++; }
      });
      this.save(); return { imported };
    }
    if (method === 'GET' && p === '/conversations') return d.conversations.filter(c => !url.searchParams.get('dataset') || c.dataset === url.searchParams.get('dataset')).map(c => {
      const ev = d.evaluations.filter(e => e.conversation_id === c.conversation_id).at(-1);
      return { conversation_id: c.conversation_id, dataset: c.dataset, channel: c.channel, language: c.language, message_count: c.transcript.length, latest_evaluation: ev ? { id: ev.id, total: ev.final.total, original_total: ev.original.total, gross_error: ev.final.gross_error, checklist_name: ev.checklist_name, checklist_version: ev.checklist_version, open_appeals: d.appeals.filter(a => a.evaluation_id === ev.id && a.status === 'open').length, decided_appeals: d.appeals.filter(a => a.evaluation_id === ev.id && a.status === 'decided').length } : null };
    });
    if (method === 'GET' && p.startsWith('/conversations/')) {
      const c = d.conversations.find(c => c.conversation_id === decodeURIComponent(p.split('/')[2]));
      if (!c) throw new Error('Диалог не найден.');
      return { ...clone(c), transcript: c.transcript.map((m, index) => ({ ...m, index })), evaluations: d.evaluations.filter(e => e.conversation_id === c.conversation_id).map(e => ({ id: e.id, created_at: e.created_at, total: e.final.total, checklist_name: e.checklist_name, checklist_version: e.checklist_version })) };
    }
    if (method === 'GET' && p === '/checklists') return clone(d.checklists);
    if (method === 'GET' && p.startsWith('/checklists/')) return clone(d.checklists.find(c => c.id === decodeURIComponent(p.split('/')[2])));
    if ((method === 'POST' && p === '/checklists') || (method === 'PUT' && p.startsWith('/checklists/'))) {
      const errors = [];
      if (!body.name?.trim()) errors.push('Укажите название чек-листа.');
      if (!body.sections?.length) errors.push('Добавьте хотя бы одну секцию.');
      if (!body.criteria?.length) errors.push('Добавьте хотя бы один критерий.');
      if (body.criteria?.some(c => !c.code?.trim() || !c.title?.trim())) errors.push('Укажите код и название каждого критерия.');
      if (new Set(body.criteria?.map(c => c.code)).size !== body.criteria?.length) errors.push('Коды критериев должны быть уникальными.');
      if (body.criteria?.some(c => c.type !== 'flag' && (!Number.isFinite(Number(c.weight)) || Number(c.weight) < 0))) errors.push('Вес должен быть неотрицательным числом.');
      if (body.criteria?.some(c => c.type === 'scale' && (!c.scale?.length || c.scale.some(s => !Number.isFinite(Number(s.value)))))) errors.push('Укажите числовые ступени каждой шкалы.');
      if (errors.length) { const error = new Error('Проверьте чек-лист.'); error.errors = errors; throw error; }
      const old = method === 'PUT' ? d.checklists.find(c => c.id === decodeURIComponent(p.split('/')[2])) : null;
      const base = old ? old.id.split('@')[0] : makeId('cl');
      const version = old ? Math.max(...d.checklists.filter(c => c.id.startsWith(`${base}@`)).map(c => c.version)) + 1 : 1;
      const checklist = { ...clone(body), id: `${base}@${version}`, version, is_default: false };
      d.checklists.push(checklist); this.save(); return clone(checklist);
    }
    if (method === 'POST' && /^\/checklists\/[^/]+\/default$/.test(p)) {
      const id = decodeURIComponent(p.split('/')[2]); d.checklists.forEach(c => { c.is_default = c.id === id; }); this.save(); return { ok: true };
    }
    if (method === 'DELETE' && p.startsWith('/checklists/')) { const c = d.checklists.find(c => c.id === decodeURIComponent(p.split('/')[2])); if (c) c.archived = true; this.save(); return { ok: true }; }
    if (method === 'POST' && p === '/evaluate') {
      const c = d.conversations.find(c => c.conversation_id === body.conversation_id);
      const cl = d.checklists.find(c => c.id === body.checklist_id);
      if (!c || !cl) throw new Error('Диалог или чек-лист не найден.');
      const ev = evaluate(c, cl); d.evaluations.push(ev); this.save(); return clone(ev);
    }
    if (method === 'POST' && p === '/evaluate/batch') {
      const ids = body.conversation_ids || d.conversations.filter(c => !body.dataset || c.dataset === body.dataset).map(c => c.conversation_id);
      const job_id = makeId('job'); d.jobs[job_id] = { status: 'running', done: 0, total: ids.length, errors: [], ids, checklist_id: body.checklist_id }; this.save(); return { job_id };
    }
    if (method === 'GET' && p.startsWith('/jobs/')) {
      const job = d.jobs[p.split('/')[2]]; if (!job) throw new Error('Задание не найдено.');
      if (job.status === 'running') { const id = job.ids[job.done]; try { if (id) await this.request('POST', '/api/evaluate', { conversation_id: id, checklist_id: job.checklist_id }); } catch (error) { job.errors.push(String(error.message)); } job.done++; if (job.done >= job.total) job.status = 'done'; this.save(); }
      return { status: job.status, done: Math.min(job.done, job.total), total: job.total, errors: job.errors };
    }
    if (method === 'GET' && p.startsWith('/evaluations/')) { const ev = d.evaluations.find(e => e.id === p.split('/')[2]); if (!ev) throw new Error('Оценка не найдена.'); return clone(ev); }
    if (method === 'POST' && p === '/appeals') {
      if (!body.comment?.trim()) throw new Error('Напишите комментарий к апелляции.');
      const ev = d.evaluations.find(e => e.id === body.evaluation_id); const criterion = ev?.criteria.find(c => c.criterion_id === body.criterion_id);
      if (!criterion) throw new Error('Критерий не найден.');
      if (criterion.appeal?.status === 'open') throw new Error('По этому критерию уже есть открытая апелляция.');
      const appeal = { id: makeId('ap'), evaluation_id: ev.id, conversation_id: ev.conversation_id, criterion_id: criterion.criterion_id, criterion_title: criterion.title, original_answer: criterion.original.answer, comment: body.comment, author: body.author || 'Пользователь', created_at: now(), status: 'open', decision: null };
      d.appeals.push(appeal); criterion.appeal = clone(appeal); this.save(); return clone(appeal);
    }
    if (method === 'GET' && p === '/appeals') return clone(d.appeals.filter(a => !url.searchParams.get('status') || a.status === url.searchParams.get('status')));
    if (method === 'POST' && /^\/appeals\/[^/]+\/decision$/.test(p)) {
      const appeal = d.appeals.find(a => a.id === p.split('/')[2]); if (!appeal || appeal.status !== 'open') throw new Error('Апелляция уже закрыта или не найдена.');
      if (!body.reason?.trim()) throw new Error('Укажите причину решения.');
      const ev = d.evaluations.find(e => e.id === appeal.evaluation_id); const criterion = ev.criteria.find(c => c.criterion_id === appeal.criterion_id);
      const cl = d.checklists.find(c => c.id === ev.checklist_id); const definition = cl.criteria.find(c => c.id === criterion.criterion_id);
      if (body.action === 'change') {
        const valid = body.new_answer === 'na' ? definition.na_allowed : definition.type === 'scale' ? definition.scale.some(s => Number(s.value) === Number(body.new_answer)) : ['yes', 'no'].includes(body.new_answer);
        if (!valid) throw new Error('Недопустимый новый ответ.');
        criterion.final.answer = definition.type === 'scale' && body.new_answer !== 'na' ? Number(body.new_answer) : body.new_answer;
        criterion.final.points = pointsFor(definition, criterion.final.answer);
        criterion.na_reason = criterion.final.answer === 'na' ? body.reason : null;
      }
      appeal.status = 'decided'; appeal.decision = { action: body.action, new_answer: body.action === 'change' ? criterion.final.answer : null, reason: body.reason, reviewer: body.reviewer || 'QA', previous_answer: criterion.original.answer };
      criterion.appeal = clone(appeal); ev.final = score(ev.criteria, cl); this.save(); return { appeal: clone(appeal), evaluation: clone(ev) };
    }
    throw new Error(`Неизвестный запрос: ${method} ${p}`);
  }
}
