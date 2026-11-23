"use strict";
const $ = (id) => document.getElementById(id);
let state = null,
  sid = null,
  sending = false,
  switching = false,
  version = 0,
  lastSignature = "";
const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
async function api(path, body) {
  const r = await fetch(
    "/api" + path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const d = await r.json();
  if (!r.ok)
    throw Error(
      typeof d.detail === "string" ? d.detail : "Запрос не прошёл проверку",
    );
  return d;
}
function error(text) {
  $("error").textContent = text;
  $("error").hidden = !text;
}
function controls() {
  const busy = sending || switching || !!state?.session.processing;
  $("input").disabled = busy || !sid;
  $("send").disabled = busy || !sid;
  $("newChat").disabled = busy;
  $("sessions").disabled = busy;
  const training = state?.messages.some(
    (m) => m.role === "user" && m.response?.educational,
  );
  if (training) $("educational").checked = true;
  $("educational").disabled = busy || training;
  $("busy").hidden = !busy;
}
function section(parent, title, text) {
  if (!text || (Array.isArray(text) && !text.length)) return;
  parent.append(el("h3", title));
  if (Array.isArray(text)) {
    const list = el("ul");
    for (const t of text) list.append(el("li", t));
    parent.append(list);
  } else parent.append(el("p", text));
}
function render(next) {
  if (next.session.id !== sid) return;
  state = next;
  controls();
  refreshVersionedPlan(next);
  const signature = JSON.stringify(next);
  if (signature === lastSignature) return;
  const follow =
    window.scrollY + innerHeight >= document.documentElement.scrollHeight - 220;
  lastSignature = signature;
  $("messages").replaceChildren();
  for (const m of next.messages) {
    const n = el("article", undefined, "message " + m.role);
    n.append(
      el("div", m.role === "user" ? "Вы" : "TradeGuard", "role"),
      el("div", m.text, "text"),
    );
    if (m.response?.facts?.length)
      for (const f of m.response.facts) {
        const box = el("div", f.statement, "fact");
        const a = el("a", " Источник");
        a.href = "#source-" + f.evidence_id;
        a.onclick = () => {
          $("sourcesPanel").open = true;
        };
        box.append(a);
        n.append(box);
      }
    $("messages").append(n);
  }
  $("suggestions").hidden = next.messages.some((m) => m.role === "user");
  const latest = [...next.messages]
    .reverse()
    .find((m) => m.role === "assistant" && m.response);
  const previousPlan = [...next.messages]
    .reverse()
    .find((m) => m.role === "assistant" && m.response?.plan);
  const p = latest?.response.plan || previousPlan?.response.plan;
  const previousOnly = !!p && !latest?.response.plan;
  $("plan").replaceChildren();
  if (p) {
    $("plan").append(
      el(
        "span",
        previousOnly
          ? "Предыдущий разбор"
          : p.status === "reviewable"
            ? "План для обсуждения"
            : "Предварительный разбор",
        "badge",
      ),
      el("h2", p.hypothesis),
    );
    if (previousOnly)
      $("plan").append(
        el(
          "p",
          "Последний ответ не обновлял этот промежуточный разбор.",
          "muted",
        ),
      );
    section(
      $("plan"),
      "Инструмент и направление",
      [
        p.instrument,
        { long: "Покупка (long)", short: "Шорт" }[p.direction] || p.direction,
      ]
        .filter(Boolean)
        .join(" · "),
    );
    section($("plan"), "Главные возражения", p.counterarguments.slice(0, 2));
    section($("plan"), "Ближайшие пробелы", p.missing.slice(0, 3));
    const details = el("details");
    details.append(el("summary", "Предварительный план и ограничения"));
    section(details, "Основания", p.basis);
    section(details, "Горизонт", p.horizon);
    section(details, "Вход", p.entry);
    section(details, "Что подтверждает идею", p.confirmation);
    section(details, "Что опровергает идею", p.invalidation);
    section(details, "Выход", p.exit);
    section(details, "Риски", p.risk_notes);
    section(details, "Все недостающие данные", p.missing);
    $("plan").append(details);
  } else
    $("plan").append(
      el("p", "Промежуточные выводы появятся по мере разговора.", "muted"),
    );
  const lastRisk = [...next.messages]
    .reverse()
    .find((m) => m.role === "assistant" && m.response);
  const calc = lastRisk?.response.risk_calculation;
  $("risk").hidden = !calc;
  $("risk").replaceChildren();
  if (calc) {
    $("risk").append(el("h2", "Арифметика риска"));
    const labels = {
      risk_budget: "Лимит убытка",
      loss_per_unit: "Убыток на единицу",
      max_lots: "Лотов по лимиту",
      max_quantity: "Количество по лимиту",
      loss_at_max_quantity: "Убыток при этом количестве",
      position_loss: "Убыток указанной позиции",
      position_notional: "Стоимость позиции",
      position_risk_percent: "Риск позиции, %",
      reward_risk_ratio: "Прибыль / риск",
      potential_profit: "Потенциальная прибыль",
    };
    for (const [key, title] of Object.entries(labels))
      if (calc.values[key] !== undefined) {
        let value = Number(calc.values[key]).toLocaleString("ru-RU", {
          maximumFractionDigits: 4,
        });
        if (
          ![
            "max_lots",
            "max_quantity",
            "reward_risk_ratio",
            "position_risk_percent",
          ].includes(key)
        )
          value +=
            " " +
            ({ rub: "₽", usd: "$", eur: "€" }[calc.values.currency] ||
              calc.values.currency ||
              "");
        const metric = el("div", undefined, "metric");
        metric.append(el("span", title), el("strong", value));
        $("risk").append(metric);
      }
    if (calc.values.over_budget)
      $("risk").append(
        el(
          "p",
          "Указанная позиция превышает согласованный лимит риска.",
          "risk-value",
        ),
      );
    section($("risk"), "Чего не хватает", calc.missing);
    section($("risk"), "Границы расчёта", calc.notes);
    if (calc.formula) {
      const d = el("details");
      d.append(el("summary", "Формула"), el("p", calc.formula));
      $("risk").append(d);
    }
    const inp = lastRisk.response.risk_inputs;
    if (inp) {
      const d = el("details");
      d.append(el("summary", "Распознанные параметры"));
      for (const [k, v] of Object.entries(inp))
        if (v && typeof v === "object")
          d.append(el("p", `${k}: ${v.value} · «${v.quote}»`));
      $("risk").append(d);
    }
  }
  $("sources").replaceChildren();
  $("sourceCount").textContent = next.evidence.length;
  for (const e of [...next.evidence].reverse()) {
    const n = el("article", undefined, "source");
    n.id = "source-" + e.id;
    const toolTitle={search:'Поиск бумаги',quote:'Котировка',history:'История цены',news:'Новости',spec:'Спецификация',web:'Документы в интернете'}[e.kind] || e.kind;
    let resultTitle=e.status==='ok'?'ответ получен':'источник недоступен';
    if(e.status==='ok' && e.kind==='search' && !e.result?.instruments?.length)resultTitle='совпадений не найдено';
    if(e.status==='ok' && e.kind==='web' && !e.result?.sources?.some(s=>s.status==='retrieved'))resultTitle='документы не получены';
    n.append(
      el(
        "strong",
        `${toolTitle} · ${resultTitle}${e.synthetic ? ' · ТЕСТОВЫЕ ДАННЫЕ' : ''}`,
      ),
      el(
        "p",
        new Date(e.observed_at).toLocaleString("ru-RU", {
          timeZone: "Europe/Moscow",
        }) + " МСК",
        "meta",
      ),
    );
    for (const c of e.calls || [])
      n.append(el("p", `${c.name} · ${c.status}`, "meta"));
    if (e.error) n.append(el("p", e.error));
    for (const source of e.result?.sources || []) {
      const a = el("a", source.title || source.url);
      try {
        const u = new URL(source.url);
        if (u.protocol === "https:") {
          a.href = u.href;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
        }
      } catch {}
      n.append(a, el("p", source.status));
    }
    const d = el("details");
    d.append(
      el("summary", "Параметры и исходный ответ"),
      el("pre", JSON.stringify(e, null, 2)),
    );
    n.append(d);
    $("sources").append(n);
  }
  if (follow)
    requestAnimationFrame(() =>
      $("composer").scrollIntoView({ block: "end", behavior: "smooth" }),
    );
}
async function list() {
  const rows = await api("/sessions");
  $("sessions").replaceChildren();
  for (const s of rows) $("sessions").add(new Option(s.title, s.id));
  $("sessions").value = sid;
}
async function open(id) {
  if (sending || switching) return;
  switching = true;
  version++;
  controls();
  try {
    const d = await api("/sessions/" + id);
    sid = id;
    $("educational").checked = d.messages.some(
      (m) => m.role === "user" && m.response?.educational,
    );
    localStorage.setItem("tradeguardSession", sid);
    lastSignature = "";
    render(d);
    await list();
    error("");
  } catch (e) {
    error(e.message);
  } finally {
    switching = false;
    controls();
  }
}
async function fresh() {
  if (sending || switching) return;
  switching = true;
  version++;
  controls();
  try {
    const d = await api("/sessions", {});
    sid = d.session.id;
    localStorage.setItem("tradeguardSession", sid);
    $("educational").checked = false;
    lastSignature = "";
    render(d);
    await list();
    error("");
  } catch (e) {
    error(e.message);
  } finally {
    switching = false;
    controls();
  }
}
$("composer").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("input").value.trim();
  if (!text || sending || switching || state?.session.processing) return;
  sending = true;
  version++;
  controls();
  error("");
  const optimistic = el("article", undefined, "message user");
  optimistic.append(el("div", "Вы", "role"), el("div", text, "text"));
  $("messages").append(optimistic);
  $("input").value = "";
  try {
    const d = await api(`/sessions/${sid}/messages`, {
      text,
      request_id: crypto.randomUUID(),
      educational: $("educational").checked,
    });
    version++;
    render(d);
    await list();
  } catch (err) {
    error(
      err.message +
        " Сообщение могло сохраниться — проверьте историю перед повтором.",
    );
  } finally {
    sending = false;
    controls();
  }
};
$("input").onkeydown = (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
};
$("newChat").onclick = fresh;
$("sessions").onchange = (e) => open(e.target.value);
document.querySelectorAll("#suggestions button").forEach(
  (b) =>
    (b.onclick = () => {
      $("input").value = b.textContent;
      $("educational").checked = true;
      $("input").focus();
    }),
);
controls();
(async () => {
  try {
    const health = await api("/health");
    automaticMonitoring = health.monitoring_enabled;
    if (health.data_source.includes("TEST DOUBLE")) {
      $("dataMode").textContent = "Учебный стенд: ответы и рыночные данные заменены тестовыми примерами.";
      $("dataMode").hidden = false;
    }
    const rows = await api("/sessions");
    const saved = localStorage.getItem("tradeguardSession");
    if (rows.some((s) => s.id === saved)) await open(saved);
    else if (rows.length) await open(rows[0].id);
    else await fresh();
    setInterval(async () => {
      if (!sid || switching) return;
      const v = version,
        id = sid;
      try {
        const d = await api("/sessions/" + id);
        if (v === version && id === sid) render(d);
      } catch {
        error("Нет связи с сервером TradeGuard. История сохранена на сервере.");
      }
    }, 3000);
  } catch (e) {
    error(e.message);
  }
})();
