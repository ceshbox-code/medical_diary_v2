/*
 * Медицинский дневник — вкладка «Лекарства» (шаг 2): график приёма на сегодня,
 * отметки «принял / пропустил», список лекарств и напоминания об измерениях.
 *
 * Файл самодостаточен: не использует переменные app.js (только глобальную
 * showToast, если она есть) и сам читает CSRF-токен из <meta name="csrf-token">.
 * Весь пользовательский текст выводится через textContent (никакого innerHTML).
 *
 * Различие «факт» и «расчёт»: состояния taken/skipped — записанные отметки
 * пользователя; «Не отмечено» (unmarked) — расчёт сервера по времени и НЕ
 * означает, что лекарство не принято.
 */
(function () {
  'use strict';

  var root = document.getElementById('page-meds');
  if (!root) { return; }

  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfMeta ? csrfMeta.content : '';

  var UNITS = ['мг', 'мкг', 'г', 'мл', 'шт', 'капли', 'ЕД'];
  var DAY_NAMES = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
  var KINDS = [
    ['glucose', 'Глюкоза'], ['vitals', 'Давление и пульс'], ['weight', 'Вес'],
    ['temperature', 'Температура'], ['food', 'Питание'], ['custom', 'Своё']
  ];
  var KIND_ICON = { glucose: '💧', vitals: '♥', weight: '⚖️', temperature: '🌡️', food: '🍴', custom: '🔔' };
  var KIND_DEFAULT_TITLE = {
    glucose: 'Измерить глюкозу', vitals: 'Измерить давление и пульс', weight: 'Взвеситься',
    temperature: 'Измерить температуру', food: 'Записать приём пищи', custom: ''
  };

  var state = { meds: [], reminders: [], schedule: null, marking: null };
  var loadSeq = 0;

  /* ------------------------------------------------------------ утилиты */

  function $(id) { return document.getElementById(id); }
  function pad(n) { return String(n).padStart(2, '0'); }
  function localDate() {
    var d = new Date();
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }
  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) { e.className = cls; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }
  function clear(el) { while (el.firstChild) { el.removeChild(el.firstChild); } }
  function toast(text, ok) { if (typeof showToast === 'function') { showToast(text, ok); } }
  function uuid() {
    if (window.crypto && window.crypto.randomUUID) { return window.crypto.randomUUID(); }
    return 'idem-' + Date.now() + '-' + Math.random().toString(36).slice(2);
  }
  function fmtNum(v) { return String(v).replace('.', ','); }
  function fmtDose(v, u) { return (v === null || v === undefined) ? '' : fmtNum(v) + '\u00a0' + (u || ''); }
  function fmtDayList(days) {
    if (!days || days.length === 7) { return 'каждый день'; }
    return days.map(function (d) { return DAY_NAMES[d]; }).join(', ');
  }
  function fmtStamp(s) {
    // 'YYYY-MM-DD HH:MM:SS' -> 'DD.MM HH:MM'
    if (!s) { return ''; }
    return s.slice(8, 10) + '.' + s.slice(5, 7) + ' ' + s.slice(11, 16);
  }
  function fmtDate(s) {
    if (!s) { return ''; }
    return s.slice(8, 10) + '.' + s.slice(5, 7) + '.' + s.slice(0, 4);
  }
  function joinParts(parts) { return parts.filter(function (p) { return p; }).join(' · '); }

  async function api(method, url, body, idemKey) {
    var opts = { method: method, headers: { 'X-CSRF-Token': csrf } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    if (idemKey) { opts.headers['Idempotency-Key'] = idemKey; }
    var res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      throw new Error('Нет соединения с сервером — проверьте интернет и попробуйте ещё раз.');
    }
    if (res.status === 401) { window.location = '/login'; throw new Error('Требуется вход'); }
    var out = {};
    try { out = await res.json(); } catch (e) { /* не JSON */ }
    if (!res.ok) { throw new Error(out.error || ('HTTP ' + res.status)); }
    return out;
  }

  function setMsg(id, text, ok) {
    var el = $(id);
    if (!el) { return; }
    el.textContent = text || '';
    el.className = 'message ' + (ok ? 'ok' : 'error');
  }

  /* ------------------------------------------------------- модальные окна */

  var MODALS = ['med-modal', 'rem-modal', 'intake-modal'];
  function openModal(id) { $(id).hidden = false; document.body.style.overflow = 'hidden'; }
  function closeModal(id) {
    var m = $(id);
    if (m) { m.hidden = true; }
    var anyOpen = MODALS.some(function (x) { var e = $(x); return e && !e.hidden; });
    if (!anyOpen) { document.body.style.overflow = ''; }
  }
  function anyModalOpen() { return MODALS.some(function (x) { var e = $(x); return e && !e.hidden; }); }

  /* -------------------------------------------------- чипы дней и времена */

  function buildDayChips(container, prefix, days) {
    clear(container);
    for (var i = 0; i < 7; i++) {
      var inp = h('input');
      inp.type = 'checkbox';
      inp.id = prefix + '-d' + i;
      inp.value = String(i);
      inp.checked = days.indexOf(i) !== -1;
      var lab = h('label', null, DAY_NAMES[i]);
      lab.htmlFor = inp.id;
      container.appendChild(inp);
      container.appendChild(lab);
    }
  }
  function readDayChips(container) {
    return Array.prototype.filter.call(container.querySelectorAll('input'), function (x) { return x.checked; })
      .map(function (x) { return parseInt(x.value, 10); });
  }

  function addTimeRow(value) {
    var box = $('med-times');
    var row = h('div', 'time-row');
    var inp = h('input');
    inp.type = 'time';
    inp.value = value || '';
    inp.setAttribute('aria-label', 'Время приёма');
    var del = h('button', 'med-btn', '×');
    del.type = 'button';
    del.setAttribute('aria-label', 'Убрать время');
    del.addEventListener('click', function () { box.removeChild(row); });
    row.appendChild(inp);
    row.appendChild(del);
    box.appendChild(row);
  }
  function readTimes() {
    return Array.prototype.map.call($('med-times').querySelectorAll('input'), function (x) { return x.value; })
      .filter(function (v) { return v; });
  }

  /* ----------------------------------------------------------- загрузка */

  function setStatus(text) {
    var el = $('meds-status');
    if (!el) { return; }
    el.textContent = text || '';
    el.className = 'message ' + (text ? 'error' : '');
  }

  async function load() {
    var seq = ++loadSeq;
    var day = localDate();
    var label = $('meds-date-label');
    if (label) { label.textContent = 'Сегодня, ' + fmtDate(day); }
    try {
      var r = await Promise.all([
        api('GET', '/api/medication-schedule?date=' + day),
        api('GET', '/api/medications'),
        api('GET', '/api/reminders')
      ]);
      if (seq !== loadSeq) { return; }
      state.schedule = r[0];
      state.meds = r[1].medications || [];
      state.reminders = r[2].reminders || [];
      setStatus('');
      render();
    } catch (e) {
      if (seq === loadSeq) { setStatus(e.message); }
    }
  }

  /* ---------------------------------------------------------- отрисовка */

  function badge(kind, text) { return h('span', 'med-badge ' + kind, text); }

  function slotCard(slot) {
    var card = h('div', 'med-card');
    card.appendChild(h('div', 'med-time', slot.time));
    var body = h('div', 'med-body');
    body.appendChild(h('div', 'med-name', slot.name));
    var sub = joinParts([fmtDose(slot.dose_value, slot.dose_unit), slot.instructions]);
    if (sub) { body.appendChild(h('div', 'med-sub', sub)); }
    if (slot.state === 'taken') {
      body.appendChild(badge('taken', '✓ Принято' + (slot.taken_at ? ' в ' + slot.taken_at.slice(11, 16) : '')));
    } else if (slot.state === 'skipped') {
      body.appendChild(badge('skipped', 'Пропущено'));
    } else if (slot.state === 'unmarked') {
      body.appendChild(badge('unmarked', 'Не отмечено'));
    } else {
      body.appendChild(badge('pending', 'Ожидается'));
    }
    if (slot.comment) { body.appendChild(h('div', 'med-sub', slot.comment)); }
    card.appendChild(body);

    var actions = h('div', 'med-actions');
    if (slot.intake_id) {
      var edit = h('button', 'med-btn', 'Изменить');
      edit.type = 'button';
      edit.addEventListener('click', function () { openIntakeForSlot(slot); });
      actions.appendChild(edit);
    } else {
      var took = h('button', 'med-btn primary', 'Принял');
      took.type = 'button';
      took.addEventListener('click', function () { quickMark(slot, 'taken', [took, skip, more]); });
      var skip = h('button', 'med-btn', 'Пропустил');
      skip.type = 'button';
      skip.addEventListener('click', function () { quickMark(slot, 'skipped', [took, skip, more]); });
      var more = h('button', 'med-btn', '⋯');
      more.type = 'button';
      more.setAttribute('aria-label', 'Уточнить время или комментарий');
      more.addEventListener('click', function () { openIntakeForSlot(slot); });
      actions.appendChild(took);
      actions.appendChild(skip);
      actions.appendChild(more);
    }
    card.appendChild(actions);
    return card;
  }

  function extraCard(item) {
    var card = h('div', 'med-card');
    card.appendChild(h('div', 'med-time', (item.taken_at || '').slice(11, 16)));
    var body = h('div', 'med-body');
    body.appendChild(h('div', 'med-name', item.medication_name));
    var dose = fmtDose(item.dose_value, item.dose_unit);
    if (dose) { body.appendChild(h('div', 'med-sub', dose)); }
    body.appendChild(badge('taken', '✓ Принято вне графика'));
    if (item.comment) { body.appendChild(h('div', 'med-sub', item.comment)); }
    card.appendChild(body);
    var actions = h('div', 'med-actions');
    var edit = h('button', 'med-btn', 'Изменить');
    edit.type = 'button';
    edit.addEventListener('click', function () { openIntakeForExtra(item); });
    actions.appendChild(edit);
    card.appendChild(actions);
    return card;
  }

  function renderToday() {
    var box = $('meds-today');
    clear(box);
    var s = state.schedule;
    if (!s) { return; }
    if (!s.slots.length && !s.unscheduled.length) {
      box.appendChild(h('div', 'muted', state.meds.length
        ? 'На сегодня приёмов по графику нет.'
        : 'Пока нет лекарств. Добавьте первое ниже.'));
      return;
    }
    s.slots.forEach(function (slot) { box.appendChild(slotCard(slot)); });
    if (s.unscheduled.length) {
      box.appendChild(h('div', 'meds-subhead', 'Вне графика'));
      s.unscheduled.forEach(function (it) { box.appendChild(extraCard(it)); });
    }
  }

  function renderMeds() {
    var box = $('meds-list');
    clear(box);
    if (!state.meds.length) { box.appendChild(h('div', 'muted', 'Список пуст.')); return; }
    state.meds.forEach(function (m) {
      var card = h('div', 'med-card' + (m.is_active ? '' : ' inactive'));
      var body = h('div', 'med-body med-body-wide');
      body.appendChild(h('div', 'med-name', m.name));
      var sub = joinParts([fmtDose(m.dose_value, m.dose_unit), m.instructions]);
      if (sub) { body.appendChild(h('div', 'med-sub', sub)); }
      var when = m.times.length ? m.times.join(', ') + ' · ' + fmtDayList(m.days) : 'без графика (по мере необходимости)';
      body.appendChild(h('div', 'med-sub', when));
      if (m.end_date) { body.appendChild(h('div', 'med-sub', 'до ' + fmtDate(m.end_date))); }
      if (!m.is_active) { body.appendChild(badge('skipped', 'Приостановлено')); }
      card.appendChild(body);
      var actions = h('div', 'med-actions');
      var now = h('button', 'med-btn', 'Принял сейчас');
      now.type = 'button';
      now.addEventListener('click', function () { markNow(m, now); });
      var edit = h('button', 'med-btn', 'Изменить');
      edit.type = 'button';
      edit.addEventListener('click', function () { openMedModal(m); });
      actions.appendChild(now);
      actions.appendChild(edit);
      card.appendChild(actions);
      box.appendChild(card);
    });
  }

  function renderReminders() {
    var box = $('rem-list');
    clear(box);
    if (!state.reminders.length) { box.appendChild(h('div', 'muted', 'Напоминаний пока нет.')); return; }
    state.reminders.forEach(function (r) {
      var card = h('div', 'med-card rem-card' + (r.is_active ? '' : ' inactive'));
      card.appendChild(h('div', 'med-time', r.time));
      var body = h('div', 'med-body');
      body.appendChild(h('div', 'med-name', (KIND_ICON[r.kind] || '🔔') + ' ' + r.title));
      body.appendChild(h('div', 'med-sub', fmtDayList(r.days)));
      card.appendChild(body);

      var actions = h('div', 'med-actions');
      var edit = h('button', 'med-btn', 'Изменить');
      edit.type = 'button';
      edit.addEventListener('click', function () { openRemModal(r); });
      var sw = h('label', 'switch-row rem-switch');
      var cb = h('input');
      cb.type = 'checkbox';
      cb.checked = r.is_active;
      cb.setAttribute('aria-label', 'Напоминание включено');
      var knob = h('span', 'switch');
      cb.addEventListener('change', function () { toggleReminder(r, cb); });
      sw.appendChild(cb);
      sw.appendChild(knob);
      actions.appendChild(edit);
      actions.appendChild(sw);
      card.appendChild(actions);
      box.appendChild(card);
    });
  }

  function render() { renderToday(); renderMeds(); renderReminders(); }

  /* ------------------------------------------------------ быстрые отметки */

  async function quickMark(slot, status, buttons) {
    buttons.forEach(function (b) { b.disabled = true; });
    try {
      await api('POST', '/api/medication-intakes',
        { medication_id: slot.medication_id, scheduled_at: slot.scheduled_at, status: status },
        'intake-' + uuid());
      toast(status === 'taken' ? 'Приём отмечен' : 'Пропуск отмечен', true);
    } catch (e) {
      toast(e.message, false);
    }
    load();
  }

  async function markNow(med, btn) {
    var dose = fmtDose(med.dose_value, med.dose_unit);
    if (!window.confirm('Записать приём «' + med.name + '»' + (dose ? ' (' + dose + ')' : '') + ' сейчас?')) { return; }
    btn.disabled = true;
    try {
      await api('POST', '/api/medication-intakes', { medication_id: med.id, status: 'taken' }, 'intake-' + uuid());
      toast('Приём записан', true);
    } catch (e) {
      toast(e.message, false);
    }
    btn.disabled = false;
    load();
  }

  async function toggleReminder(r, cb) {
    var want = cb.checked;
    try {
      await api('PATCH', '/api/reminders/' + r.id, { is_active: want });
      r.is_active = want;
      cb.closest('.med-card').classList.toggle('inactive', !want);
    } catch (e) {
      cb.checked = !want;
      toast(e.message, false);
    }
  }

  /* ---------------------------------------------------- окно отметки приёма */

  var intakeCtx = null;

  function openIntakeCommon(ctx, title, sub) {
    intakeCtx = ctx;
    $('intake-title').textContent = title;
    $('intake-sub').textContent = sub;
    $('ik_taken').checked = ctx.status !== 'skipped';
    $('ik_skipped').checked = ctx.status === 'skipped';
    $('intake-status-group').hidden = !ctx.canSkip;
    $('intake-time').value = ctx.time || '';
    $('intake-comment').value = ctx.comment || '';
    $('intake-delete').hidden = !ctx.intakeId;
    setMsg('intake-msg', '', true);
    syncIntakeTimeVisibility();
    openModal('intake-modal');
  }

  function syncIntakeTimeVisibility() {
    $('intake-time-wrap').hidden = $('ik_skipped').checked;
  }

  function openIntakeForSlot(slot) {
    openIntakeCommon({
      intakeId: slot.intake_id,
      medicationId: slot.medication_id,
      scheduledAt: slot.scheduled_at,
      baseDate: (slot.taken_at || slot.scheduled_at).slice(0, 10),
      canSkip: true,
      status: slot.state === 'skipped' ? 'skipped' : 'taken',
      time: slot.taken_at ? slot.taken_at.slice(11, 16) : '',
      comment: slot.comment,
      idem: 'intake-' + uuid()
    }, slot.name, joinParts(['по графику ' + slot.time, fmtDose(slot.dose_value, slot.dose_unit)]));
  }

  function openIntakeForExtra(item) {
    openIntakeCommon({
      intakeId: item.id,
      medicationId: item.medication_id,
      scheduledAt: null,
      baseDate: (item.taken_at || '').slice(0, 10),
      canSkip: false,
      status: 'taken',
      time: (item.taken_at || '').slice(11, 16),
      comment: item.comment,
      idem: null
    }, item.medication_name, joinParts(['вне графика', fmtDose(item.dose_value, item.dose_unit)]));
  }

  async function saveIntake(ev) {
    ev.preventDefault();
    var c = intakeCtx;
    if (!c) { return; }
    var status = $('ik_skipped').checked ? 'skipped' : 'taken';
    var time = $('intake-time').value;
    var comment = $('intake-comment').value.trim();
    var btn = $('intake-save');
    btn.disabled = true;
    try {
      if (c.intakeId) {
        var upd = { status: status, comment: comment };
        if (status === 'taken' && time) { upd.taken_at = c.baseDate + ' ' + time; }
        await api('PATCH', '/api/medication-intakes/' + c.intakeId, upd);
      } else {
        var create = { medication_id: c.medicationId, scheduled_at: c.scheduledAt, status: status, comment: comment };
        if (status === 'taken' && time) { create.taken_at = c.baseDate + ' ' + time; }
        await api('POST', '/api/medication-intakes', create, c.idem);
      }
      closeModal('intake-modal');
      toast('Сохранено', true);
      load();
    } catch (e) {
      setMsg('intake-msg', e.message, false);
    }
    btn.disabled = false;
  }

  async function deleteIntake() {
    var c = intakeCtx;
    if (!c || !c.intakeId) { return; }
    if (!window.confirm('Снять отметку? Запись о приёме будет удалена.')) { return; }
    try {
      await api('DELETE', '/api/medication-intakes/' + c.intakeId);
      closeModal('intake-modal');
      toast('Отметка снята', true);
      load();
    } catch (e) {
      setMsg('intake-msg', e.message, false);
    }
  }

  /* ------------------------------------------------------ окно лекарства */

  var medCtx = null;

  function openMedModal(med) {
    medCtx = { id: med ? med.id : null, idem: med ? null : 'med-' + uuid(), marking: null };
    $('med-modal-title').textContent = med ? 'Изменить лекарство' : 'Новое лекарство';
    $('med-scan-status').textContent = '';
    $('med-marking-preview').hidden = true;
    $('med-marking-preview').textContent = '';
    $('med-name').value = med ? med.name : '';
    $('med-dose').value = med && med.dose_value !== null ? fmtNum(med.dose_value) : '';
    var unitSel = $('med-unit');
    if (!unitSel.options.length) {
      UNITS.forEach(function (u) { var o = h('option', null, u); o.value = u; unitSel.appendChild(o); });
    }
    unitSel.value = med && med.dose_unit ? med.dose_unit : UNITS[0];
    $('med-instr').value = med ? med.instructions : '';
    clear($('med-times'));
    (med ? med.times : ['08:00']).forEach(addTimeRow);
    buildDayChips($('med-days'), 'med', med ? med.days : [0, 1, 2, 3, 4, 5, 6]);
    $('med-start').value = med ? med.start_date : localDate();
    $('med-end').value = med && med.end_date ? med.end_date : '';
    $('med-comment').value = med ? med.comment : '';
    $('med-active').checked = med ? med.is_active : true;
    $('med-delete').hidden = !med;
    setMsg('med-msg', '', true);
    openModal('med-modal');
  }

  async function saveMed(ev) {
    ev.preventDefault();
    var name = $('med-name').value.trim();
    var doseRaw = $('med-dose').value.trim().replace(',', '.');
    if (!name) { setMsg('med-msg', 'Название: заполните поле', false); return; }
    if (doseRaw && !/^\d+(\.\d+)?$/.test(doseRaw)) { setMsg('med-msg', 'Доза: введите число', false); return; }
    var days = readDayChips($('med-days'));
    if (!days.length) { setMsg('med-msg', 'Дни недели: выберите хотя бы один день', false); return; }
    var payload = {
      name: name,
      dose_value: doseRaw,
      dose_unit: doseRaw ? $('med-unit').value : '',
      instructions: $('med-instr').value.trim(),
      times: readTimes(),
      days: days,
      start_date: $('med-start').value,
      end_date: $('med-end').value,
      comment: $('med-comment').value.trim(),
      is_active: $('med-active').checked
    };
    if (medCtx.marking) { payload.marking = medCtx.marking; }
    var btn = $('med-save');
    btn.disabled = true;
    try {
      if (medCtx.id) { await api('PATCH', '/api/medications/' + medCtx.id, payload); }
      else { await api('POST', '/api/medications', payload, medCtx.idem); }
      closeModal('med-modal');
      toast('Сохранено', true);
      load();
    } catch (e) {
      setMsg('med-msg', e.message, false);
    }
    btn.disabled = false;
  }

  async function deleteMed() {
    if (!medCtx || !medCtx.id) { return; }
    if (!window.confirm('Удалить лекарство? История приёмов сохранится.')) { return; }
    try {
      await api('DELETE', '/api/medications/' + medCtx.id);
      closeModal('med-modal');
      toast('Лекарство удалено', true);
      load();
    } catch (e) {
      setMsg('med-msg', e.message, false);
    }
  }

  /* ---------------------------------------------------- окно напоминания */

  var remCtx = null;

  function updateRemTitleHint() {
    var kind = $('rem-kind').value;
    $('rem-title').placeholder = KIND_DEFAULT_TITLE[kind] || 'Например: Пить воду';
  }

  function openRemModal(rem) {
    remCtx = { id: rem ? rem.id : null, idem: rem ? null : 'rem-' + uuid() };
    $('rem-modal-title').textContent = rem ? 'Изменить напоминание' : 'Новое напоминание';
    var kindSel = $('rem-kind');
    if (!kindSel.options.length) {
      KINDS.forEach(function (k) { var o = h('option', null, k[1]); o.value = k[0]; kindSel.appendChild(o); });
    }
    kindSel.value = rem ? rem.kind : 'glucose';
    $('rem-title').value = rem && rem.title !== KIND_DEFAULT_TITLE[rem.kind] ? rem.title : '';
    updateRemTitleHint();
    $('rem-time').value = rem ? rem.time : '08:00';
    buildDayChips($('rem-days'), 'rem', rem ? rem.days : [0, 1, 2, 3, 4, 5, 6]);
    $('rem-active').checked = rem ? rem.is_active : true;
    $('rem-delete').hidden = !rem;
    setMsg('rem-msg', '', true);
    openModal('rem-modal');
  }

  async function saveRem(ev) {
    ev.preventDefault();
    var days = readDayChips($('rem-days'));
    if (!days.length) { setMsg('rem-msg', 'Дни недели: выберите хотя бы один день', false); return; }
    if (!$('rem-time').value) { setMsg('rem-msg', 'Время: укажите время', false); return; }
    var payload = {
      kind: $('rem-kind').value,
      title: $('rem-title').value.trim(),
      time: $('rem-time').value,
      days: days,
      is_active: $('rem-active').checked
    };
    var btn = $('rem-save');
    btn.disabled = true;
    try {
      if (remCtx.id) { await api('PATCH', '/api/reminders/' + remCtx.id, payload); }
      else { await api('POST', '/api/reminders', payload, remCtx.idem); }
      closeModal('rem-modal');
      toast('Сохранено', true);
      load();
    } catch (e) {
      setMsg('rem-msg', e.message, false);
    }
    btn.disabled = false;
  }

  async function deleteRem() {
    if (!remCtx || !remCtx.id) { return; }
    if (!window.confirm('Удалить напоминание?')) { return; }
    try {
      await api('DELETE', '/api/reminders/' + remCtx.id);
      closeModal('rem-modal');
      toast('Напоминание удалено', true);
      load();
    } catch (e) {
      setMsg('rem-msg', e.message, false);
    }
  }


  /* -------------------------------------------- сканирование Data Matrix */

  var scanStream = null;
  var scanTimer = null;
  var scanBusy = false;

  function stopMedScanner() {
    if (scanTimer) { clearInterval(scanTimer); scanTimer = null; }
    if (scanStream) {
      scanStream.getTracks().forEach(function (track) { track.stop(); });
      scanStream = null;
    }
    var video = $('med-scan-video');
    if (video) { video.srcObject = null; }
  }

  function closeMedScanner() {
    stopMedScanner();
    $('med-scan-modal').hidden = true;
    document.body.style.overflow = '';
  }

  async function submitScannedCode(code) {
    code = String(code || '').trim();
    if (!code) { setMsg('med-scan-msg', 'Код не указан', false); return; }
    if (code.length > 4096) { setMsg('med-scan-msg', 'Код слишком длинный', false); return; }
    if (scanBusy) { return; }
    scanBusy = true;
    setMsg('med-scan-msg', 'Проверяю код…', true);
    try {
      var out = await api('POST', '/api/medications/scan', { code: code });
      medCtx.marking = { raw: out.marking.raw };
      $('med-marking-preview').hidden = false;
      $('med-marking-preview').textContent =
        '✓ Код распознан · GTIN ' + out.marking.gtin +
        ' · серия ' + out.marking.serial_number +
        (out.marking.already_registered ? ' · уже зарегистрирован' : '');
      $('med-scan-status').textContent = 'Код Честного знака привязан к новой записи.';
      if (out.marking.already_registered) {
        setMsg('med-scan-msg', 'Эта упаковка уже есть в дневнике. Создайте другую запись или используйте существующую.', false);
        return;
      }
      setMsg('med-scan-msg', 'Код принят. Теперь заполните название лекарства и сохраните запись.', true);
      closeMedScanner();
    } catch (e) {
      setMsg('med-scan-msg', e.message, false);
    } finally {
      scanBusy = false;
    }
  }

  async function openMedScanner() {
    $('med-scan-modal').hidden = false;
    document.body.style.overflow = 'hidden';
    setMsg('med-scan-msg', '', true);
    $('med-scan-hint').textContent = 'Проверяю поддержку Data Matrix…';
    if (!('BarcodeDetector' in window)) {
      $('med-scan-hint').textContent = 'Автоматическое сканирование не поддерживается этим браузером. Вставьте строку Data Matrix ниже.';
      return;
    }
    try {
      var formats = await BarcodeDetector.getSupportedFormats();
      if (formats.indexOf('data_matrix') === -1) {
        $('med-scan-hint').textContent = 'Браузер не поддерживает Data Matrix. Вставьте строку кода вручную.';
        return;
      }
      scanStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false
      });
      var video = $('med-scan-video');
      video.srcObject = scanStream;
      await video.play();
      $('med-scan-hint').textContent = 'Наведите заднюю камеру на Data Matrix. После распознавания камера будет остановлена.';
      var detector = new BarcodeDetector({ formats: ['data_matrix'] });
      scanTimer = setInterval(async function () {
        if (scanBusy || video.readyState < 2 || !video.videoWidth) { return; }
        try {
          var codes = await detector.detect(video);
          if (codes && codes.length && codes[0].rawValue) {
            await submitScannedCode(codes[0].rawValue);
          }
        } catch (e) { /* следующий кадр */ }
      }, 250);
    } catch (e) {
      stopMedScanner();
      $('med-scan-hint').textContent = 'Не удалось открыть камеру. Проверьте разрешение камеры и HTTPS. Код можно вставить вручную.';
      setMsg('med-scan-msg', 'Камера недоступна', false);
    }
  }
\n  /* -------------------------------------------------------------- история */

  async function loadHistory() {
    var box = $('meds-history');
    clear(box);
    box.appendChild(h('div', 'muted', 'Загрузка…'));
    try {
      var out = await api('GET', '/api/medication-intakes');
      clear(box);
      var list = out.intakes || [];
      if (!list.length) { box.appendChild(h('div', 'muted', 'За 30 дней отметок нет.')); return; }
      list.forEach(function (it) {
        var row = h('div', 'med-hist');
        row.appendChild(h('div', 'med-hist-time', fmtStamp(it.scheduled_at || it.taken_at)));
        var body = h('div', 'med-body');
        body.appendChild(h('div', 'med-name', it.medication_name));
        var sub = joinParts([fmtDose(it.dose_value, it.dose_unit), it.scheduled_at ? '' : 'вне графика']);
        if (sub) { body.appendChild(h('div', 'med-sub', sub)); }
        body.appendChild(it.status === 'taken'
          ? badge('taken', '✓ Принято' + (it.taken_at ? ' в ' + it.taken_at.slice(11, 16) : ''))
          : badge('skipped', 'Пропущено'));
        if (it.comment) { body.appendChild(h('div', 'med-sub', it.comment)); }
        row.appendChild(body);
        box.appendChild(row);
      });
    } catch (e) {
      clear(box);
      box.appendChild(h('div', 'message error', e.message));
    }
  }

  /* --------------------------------------------------------- привязка событий */

  $('med-add-btn').addEventListener('click', function () { openMedModal(null); });
  $('med-scan-btn').addEventListener('click', openMedScanner);
  $('med-scan-close').addEventListener('click', closeMedScanner);
  $('med-scan-manual').addEventListener('click', function () { submitScannedCode($('med-scan-code').value); });
  $('med-scan-modal').addEventListener('click', function (e) { if (e.target === this) { closeMedScanner(); } });
  $('rem-add-btn').addEventListener('click', function () { openRemModal(null); });
  $('med-time-add').addEventListener('click', function () { addTimeRow(''); });
  $('med-form').addEventListener('submit', saveMed);
  $('med-delete').addEventListener('click', deleteMed);
  $('rem-form').addEventListener('submit', saveRem);
  $('rem-delete').addEventListener('click', deleteRem);
  $('rem-kind').addEventListener('change', updateRemTitleHint);
  $('intake-form').addEventListener('submit', saveIntake);
  $('intake-delete').addEventListener('click', deleteIntake);
  $('ik_taken').addEventListener('change', syncIntakeTimeVisibility);
  $('ik_skipped').addEventListener('change', syncIntakeTimeVisibility);
  $('meds-history-details').addEventListener('toggle', function () {
    if ($('meds-history-details').open) { loadHistory(); }
  });

  Array.prototype.forEach.call(document.querySelectorAll('[data-close]'), function (btn) {
    btn.addEventListener('click', function () { closeModal(btn.getAttribute('data-close')); });
  });
  MODALS.forEach(function (id) {
    $(id).addEventListener('click', function (e) { if (e.target === this) { closeModal(id); } });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { MODALS.forEach(closeModal); }
  });

  // Обновление, пока вкладка открыта: при возврате в приложение и раз в минуту
  // (расчётное состояние «Не отмечено» меняется со временем). Пока открыто
  // окно редактирования, список не перерисовываем.
  function refreshIfVisible() {
    if (!document.hidden && !root.hidden && !anyModalOpen()) { load(); }
  }
  document.addEventListener('visibilitychange', refreshIfVisible);
  setInterval(refreshIfVisible, 60000);

  window.MedsUI = { load: load };
  if (!root.hidden) { load(); }
})();
