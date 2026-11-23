"use strict";
let planSession = null, planDocument = null, planETag = null, planLoading = false;
let planDirty = false, planBusy = false, planGeneration = 0, confirmRequest = null;
let automaticMonitoring = false;

async function planApi(path, body, method = "POST") {
  const response = await fetch("/api" + path, body === undefined ? {} : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "Проверьте поля плана");
  return { data, etag: response.headers.get("etag")?.replaceAll('"', "") };
}
function planMessage(text) {
  let box = $("planMessage");
  if (!box) { box = el("p"); box.id = "planMessage"; box.setAttribute("role", "status"); $("versionedPlan").append(box); }
  box.textContent = text;
}
async function refreshVersionedPlan(next, force = false) {
  if (planSession !== next.session.id) {
    planSession = next.session.id; planDocument = null; planETag = null;
    planDirty = false; planBusy = false; confirmRequest = null; planGeneration++;
    $("versionedPlan").replaceChildren(el("h2", "План и мониторинг"), el("p", "Сначала разберите идею или создайте пустой черновик.", "muted"));
    const create = el("button", "Создать черновик"); create.id = "createPlan"; create.type = "button";
    create.onclick = () => refreshVersionedPlan(state, true); $("versionedPlan").append(create);
  }
  if (planLoading || planBusy) return;
  const relevant = next.messages.some(m => m.role === "assistant" && (m.response?.risk_inputs || m.response?.plan));
  if (!force && !planDocument && !relevant) return;
  const generation = planGeneration, session = next.session.id;
  planLoading = true;
  try {
    const response = await planApi(`/sessions/${session}/plan`);
    if (session !== sid || generation !== planGeneration) return;
    if (!planDirty || force) {
      if (!planDocument || planDocument.version !== response.data.version || planDocument.status !== response.data.status || force) {
        planDocument = response.data; planETag = response.etag; planDirty = false; confirmRequest = null;
        renderPlanEditor();
      }
    } else if (planDocument.version !== response.data.version || planDocument.status !== response.data.status) {
      planMessage("План изменён в другом окне. Ваши несохранённые поля оставлены; обновите версию перед сохранением.");
    }
    await refreshMonitoring(generation);
  } catch (e) { if (session === sid) planMessage(e.message); }
  finally { planLoading = false; }
}
function planField(form, id, title, value = "", multiline = false, options = null) {
  const label = el("label", title, "plan-field");
  const input = el(options ? "select" : multiline ? "textarea" : "input");
  input.id = id; input.name = id;
  if (options) for (const [v, text] of options) input.add(new Option(text, v));
  if (!options && !multiline) input.type = "text";
  if (multiline) input.rows = 2;
  input.value = value ?? ""; input.maxLength = multiline ? 3000 : 180;
  label.append(input); form.append(label); return input;
}
function renderPlanEditor() {
  const p = planDocument, box = $("versionedPlan"); box.replaceChildren();
  box.append(el("h2", "План и мониторинг"), el("span", `Версия ${p.version} · ${p.status === "confirmed" ? "подтверждена" : "черновик"}${p.educational ? " · учебная" : ""}`, "badge"));
  box.append(el("p", "Подтверждение сохраняет условия и включает проверки. Решение о сделке остаётся за вами.", "muted"));
  if (p.hypothesis) box.append(el("p", p.hypothesis));
  if (p.risk?.calculation) {
    const c = p.risk.calculation;
    box.append(el("p", `Условный убыток у стопа: ${c.loss_at_stop} ${c.currency}; количество: ${c.quantity}.`, "risk-value"));
  }
  section(box, "Что мешает расчёту", p.risk?.missing);
  section(box, "Что нужно для подтверждения", p.missing);
  const assumptions = el("details"); assumptions.append(el("summary", "Ограничения расчёта"));
  section(assumptions, "Учтите", p.risk?.assumptions); box.append(assumptions);
  const details = el("details"); details.id = "planEditDetails";
  details.append(el("summary", p.status === "confirmed" ? "Изменить условия в новом черновике" : "Редактировать условия"));
  const form = el("form"); form.id = "planEditor";
  const known = new Map();
  for (const e of state.evidence) if (e.kind === "search" && e.status === "ok")
    for (const i of e.result?.instruments || []) known.set(i.id, i);
  const options = [["", "Выберите контракт из разбора"], ...[...known.values()].filter(i => ["future", "share"].includes(i.kind)).map(i => [i.id, `${i.ticker} · ${i.class_code}`])];
  planField(form, "planInstrument", "Инструмент", p.instrument?.id, false, options);
  planField(form, "planDirection", "Направление", p.direction, false, [["", "Выберите"], ["long", "Покупка (long)"], ["short", "Шорт"]]);
  planField(form, "planHypothesis", "Гипотеза", p.hypothesis, true);
  planField(form, "planHorizon", "Горизонт", p.horizon);
  for (const [key, title] of [["entry_conditions", "Условия входа"], ["exit_conditions", "Условия выхода"], ["review_conditions", "Когда пересмотреть идею"]])
    planField(form, "plan_" + key, title + " (по одному на строку)", (p[key] || []).join("\n"), true);
  const params = p.parameters || {};
  for (const [key, title] of [["entry", "Вход"], ["stop", "Стоп"], ["target", "Цель (необязательно)"], ["quantity", "Количество единиц / контрактов"], ["capital", "Капитал"], ["costs_per_unit", "Издержки на единицу (необязательно)"]])
    planField(form, "param_" + key, title, params[key]);
  planField(form, "planCurrency", "Валюта капитала", (params.capital_currency || "RUB").toUpperCase(), false, [["RUB", "RUB"], ["USD", "USD"], ["EUR", "EUR"]]);
  form.append(el("p", p.instrument?.kind === "future" ? "Цены фьючерса — в пунктах; лот и стоимость пункта проверяет сервер по спецификации." : "Цены акций — в валюте капитала; лот проверяет сервер.", "muted"));
  const limit = p.risk?.limit || {};
  planField(form, "planLimitKind", "Вид лимита", limit.kind || "percent", false, [["percent", "% капитала"], ["money", "Сумма в валюте капитала"]]);
  planField(form, "planLimit", "Лимит риска", limit.value);
  const rule = p.rules?.find(r => r.automatic) || {};
  planField(form, "planOperator", "Уведомлять, когда цена", rule.operator || (p.direction === "short" ? "gte" : "lte"), false,
    [["lte", "≤ порога"], ["gte", "≥ порога"], ["lt", "< порога"], ["gt", "> порога"]]);
  planField(form, "planThreshold", "Порог уведомления", rule.threshold || params.stop);
  planField(form, "planMaxAge", "Допустимый возраст котировки, секунд (1–3600)", rule.max_age_seconds || 300);
  const educational = el("label", " Учебный план", "plan-check"); const training = el("input");
  training.type = "checkbox"; training.id = "planEducational"; training.checked = p.educational;
  educational.prepend(training); form.append(educational);
  const save = el("button", p.status === "confirmed" ? "Сохранить новую версию" : "Сохранить изменения"); save.type = "submit"; save.id = "savePlan";
  form.append(save); details.append(form); box.append(details);
  form.oninput = () => { planDirty = true; if ($("confirmPlan")) $("confirmPlan").disabled = true; };
  form.onsubmit = async event => {
    event.preventDefault(); if (planBusy) return;
    const instrument = known.get($("planInstrument").value);
    if (!instrument) { planMessage("Сначала найдите конкретный инструмент в диалоге."); return; }
    const parameters = {};
    for (const key of ["entry", "stop", "target", "quantity", "capital", "costs_per_unit"]) {
      const value = $("param_" + key).value.trim().replace(",", "."); if (value) parameters[key] = value;
    }
    parameters.capital_currency = $("planCurrency").value;
    parameters.price_unit = instrument.kind === "future" ? "points" : parameters.capital_currency.toLowerCase();
    const spec = [...state.evidence].reverse().find(e => e.kind === "spec" && e.status === "ok" && e.result?.instrument?.id === instrument.id);
    const threshold = $("planThreshold").value.trim().replace(",", ".");
    const rules = threshold && spec ? [{ id: rule.id || "stop-price", metric: "price", operator: $("planOperator").value,
      threshold, unit: parameters.price_unit, automatic: true, max_age_seconds: Number($("planMaxAge").value), source_ids: [spec.id] }] : [];
    // Additional manual or API-created rules are retained, never silently discarded.
    rules.push(...(p.rules || []).filter(r => r.id !== rule.id));
    const changes = { instrument: Object.fromEntries(["id", "ticker", "class_code", "kind"].map(k => [k, instrument[k]])),
      hypothesis: $("planHypothesis").value.trim(), horizon: $("planHorizon").value.trim(), parameters, rules,
      educational: $("planEducational").checked,
      risk: { limit: { kind: $("planLimitKind").value, value: $("planLimit").value.trim().replace(",", "."),
        ...($("planLimitKind").value === "money" ? { currency: parameters.capital_currency } : {}) } } };
    if ($("planDirection").value) changes.direction = $("planDirection").value;
    for (const key of ["entry_conditions", "exit_conditions", "review_conditions"])
      changes[key] = $("plan_" + key).value.split("\n").map(s => s.trim()).filter(Boolean);
    await mutatePlan(() => planApi(`/plans/${p.id}`, { expected_version: p.version, changes }, "PATCH"));
  };
  if (p.status === "draft") {
    const review = el("label", " Я проверил условия и условный риск этой версии", "plan-check");
    const checkbox = el("input"); checkbox.type = "checkbox"; checkbox.id = "reviewPlan"; review.prepend(checkbox); box.append(review);
    const confirm = el("button", `Подтвердить версию ${p.version}`); confirm.id = "confirmPlan"; confirm.type = "button"; confirm.disabled = true;
    checkbox.onchange = () => { confirm.disabled = !checkbox.checked || planDirty || planBusy; };
    confirm.onclick = async () => {
      if (planBusy || planDirty || !checkbox.checked) return;
      confirmRequest ||= crypto.randomUUID();
      await mutatePlan(() => planApi(`/plans/${p.id}/confirm`, { version: p.version, content_hash: planETag, request_id: confirmRequest }));
    };
    box.append(confirm);
  }
  const reload = el("button", "Обновить версию с сервера"); reload.type = "button";
  reload.onclick = () => { if (!planBusy) refreshVersionedPlan(state, true); }; box.append(reload);
  const message = el("p"); message.id = "planMessage"; message.setAttribute("role", "status"); box.append(message);
  const monitoring = el("div"); monitoring.id = "monitoringState"; box.append(monitoring);
  const notices = el("div"); notices.id = "planNotifications"; notices.setAttribute("aria-live", "polite"); box.append(notices);
}
async function mutatePlan(action) {
  const generation = planGeneration; planBusy = true;
  const form = $("planEditor"); for (const control of form?.elements || []) control.disabled = true;
  if ($("confirmPlan")) $("confirmPlan").disabled = true;
  try {
    const response = await action();
    if (generation !== planGeneration) return;
    planDocument = response.data; planETag = response.etag; planDirty = false; confirmRequest = null;
    renderPlanEditor(); planMessage(response.data.status === "confirmed" ?
      (automaticMonitoring ? "Версия сохранена и подтверждена. Мониторинг включён." : "Версия подтверждена. Автоматические проверки отключены в настройках сервера.") :
      "Новая версия сохранена. Проверьте серверный расчёт перед подтверждением.");
    await refreshMonitoring(generation);
  } catch (e) { if (generation === planGeneration) planMessage(e.message); }
  finally {
    if (generation === planGeneration) {
      planBusy = false;
      for (const control of $("planEditor")?.elements || []) control.disabled = false;
      if ($("confirmPlan")) $("confirmPlan").disabled = planDirty || !$("reviewPlan")?.checked;
    }
  }
}
async function refreshMonitoring(generation) {
  const p = planDocument; if (!p) return;
  const [monitoring, checks, notifications] = await Promise.all([
    planApi(`/plans/${p.id}/monitoring`), planApi(`/plans/${p.id}/checks`), planApi(`/plans/${p.id}/notifications`),
  ]);
  if (generation !== planGeneration || !$("monitoringState")) return;
  const status = monitoring.data;
  $("monitoringState").replaceChildren(el("h3", "Проверки условий"), el("p", status.state === "not_started" ? "Начнутся после подтверждения." :
    `Мониторинг версии ${status.confirmed_version} · ${automaticMonitoring ? { active: "включён", paused: "приостановлен", error: "ошибка проверки, будет повторена" }[status.state] : "автоматические проверки отключены на сервере"}`));
  if (status.last_checked_at) $("monitoringState").append(el("p", `Последняя проверка: ${new Date(status.last_checked_at).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" })} МСК`));
  const labels = { satisfied: "условие выполнено", affected: "порог не достигнут", insufficient_data: "недостаточно данных", error: "ошибка" };
  for (const c of checks.data.slice(0, 5))
    $("monitoringState").append(el("p", `Версия ${c.plan_version} · ${c.rule_id === "stop-price" ? "ценовое условие" : c.rule_id}: ${labels[c.status]}${c.observed_value === null ? "" : " · " + c.observed_value}`));
  const box = $("planNotifications"); box.replaceChildren(el("h3", "Уведомления"));
  if (!notifications.data.length) box.append(el("p", "Новых уведомлений пока нет.", "muted"));
  for (const n of notifications.data.slice(0, 10)) {
    const item = el("article", undefined, "source"); item.append(el("p", n.text));
    item.append(el("p", new Date(n.created_at).toLocaleString("ru-RU", {timeZone: "Europe/Moscow"}) + " МСК", "meta"));
    const check = checks.data.find(c => c.id === n.check_id);
    if (check?.source_ids.length) {
      const link = el("a", "Источники проверки"); link.href = "#source-" + check.source_ids.at(-1);
      link.onclick = () => { $("sourcesPanel").open = true; }; item.append(link);
    }
    const delivery = el("p", n.delivery_status === "delivered" ? "Показано в интерфейсе" : n.delivery_status === "failed" ? "Ошибка доставки" : "Сохранено · ожидает показа", "meta");
    item.append(delivery); box.append(item);
    if (n.delivery_status === "stored" && !document.hidden) {
      // A stored record is acknowledged only after it has been added to this page.
      try {
        await planApi(`/plans/${p.id}/notifications/${n.id}/ack`, {});
        if (generation === planGeneration) delivery.textContent = "Показано в интерфейсе";
      } catch { delivery.textContent = "Показано · подтверждение доставки не сохранено, повторим позже"; }
    }
  }
}
