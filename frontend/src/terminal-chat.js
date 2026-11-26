(() => {
  const form = document.getElementById("dialog-form");
  const input = document.getElementById("dialog-input");
  const send = document.getElementById("dialog-send");
  const newDialog = document.getElementById("new-dialog");
  const history = document.getElementById("dialog-sessions");
  const messages = document.getElementById("dialog-messages");
  const status = document.getElementById("dialog-status");
  const storageKey = "tradeguardSession";
  const waiting = "Агент готовит ответ…";
  let state = null;
  let sessions = [];
  let busy = false;
  let pollTimer;
  let retry;

  if (location.protocol === "file:") {
    const link = document.createElement("a");
    link.href = "http://127.0.0.1:5173/terminal.html";
    link.textContent = "Открыть терминал с агентом";
    status.replaceChildren(link);
    return;
  }

  async function api(path, body) {
    let response;
    try {
      response = await fetch(`/api${path}`, body === undefined
        ? { cache: "no-store" }
        : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch {
      throw new Error("Нет связи с сервером TradeGuard.");
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const message = response.status >= 500
        ? "Сервер TradeGuard временно недоступен."
        : typeof data?.detail === "string" ? data.detail : "Запрос не прошёл проверку.";
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    if (data === null) throw new Error("Сервер TradeGuard вернул некорректный ответ.");
    return data;
  }

  function sessionPath(id) {
    return `/sessions/${encodeURIComponent(id)}`;
  }

  function showStatus(text, error = false) {
    status.textContent = text;
    status.dataset.error = String(error);
    status.hidden = !text;
  }

  function updateControls() {
    input.disabled = busy;
    send.disabled = busy || Boolean(state?.session.processing);
    newDialog.disabled = busy;
    history.disabled = busy || sessions.length === 0;
  }

  function messageNode(record) {
    const item = document.createElement("p");
    item.className = "message";
    item.classList.toggle("user-message", record.role === "user");
    item.classList.toggle("message-error", Boolean(record.response?.error));
    item.textContent = record.text;
    return item;
  }

  function updateHistory() {
    const options = sessions.map((session) => new Option(session.title, session.id));
    history.replaceChildren(...(options.length ? options : [new Option("Нет диалогов", "")]));
    history.value = state?.session.id ?? "";
  }

  function hasAnswer(next, requestId) {
    return next.messages.some((message) => message.response?.artifact_id === requestId);
  }

  function render(next) {
    const previous = state;
    state = next;
    const { session } = next;
    const index = sessions.findIndex(({ id }) => id === session.id);
    if (index === -1) sessions.unshift(session);
    else sessions[index] = session;
    updateHistory();
    if (previous?.session.id !== session.id) {
      try { localStorage.setItem(storageKey, session.id); } catch { /* Optional browser preference. */ }
    }
    if (previous?.session.id !== session.id || previous.messages.at(-1)?.id !== next.messages.at(-1)?.id) {
      messages.replaceChildren(...next.messages.map(messageNode));
      messages.scrollTop = messages.scrollHeight;
    }
    if (retry?.id === session.id && hasAnswer(next, retry.requestId)) {
      if (input.value.trim() === retry.text) input.value = "";
      retry = undefined;
    }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!state?.session.processing) return;
    const previous = state;
    pollTimer = setTimeout(async () => {
      if (busy) {
        schedulePoll();
        return;
      }
      try {
        const next = await api(sessionPath(previous.session.id));
        if (state !== previous || busy) return;
        render(next);
        showStatus(next.session.processing ? waiting : "");
        updateControls();
        schedulePoll();
      } catch (error) {
        if (state !== previous || busy) return;
        showStatus(error.message, true);
        schedulePoll();
      }
    }, 3000);
  }

  async function run(activity, action) {
    if (busy) return;
    busy = true;
    updateControls();
    showStatus(activity);
    try {
      await action();
      showStatus(state?.session.processing ? waiting : "");
    } catch (error) {
      showStatus(error.message, true);
      updateHistory();
    } finally {
      busy = false;
      updateControls();
      schedulePoll();
    }
  }

  function select(next) {
    render(next);
    input.value = "";
    retry = undefined;
  }

  newDialog.addEventListener("click", () => {
    run("Создаём диалог…", async () => select(await api("/sessions", {})));
  });

  history.addEventListener("change", () => {
    const id = history.value;
    if (!id || id === state?.session.id) return;
    run("Загружаем диалог…", async () => select(await api(sessionPath(id))));
  });

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (!send.disabled) form.requestSubmit(send);
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || state?.session.processing) return;
    run(waiting, async () => {
      if (!state) render(await api("/sessions", {}));
      const id = state.session.id;
      if (retry?.id !== id || retry.text !== text) {
        retry = { id, text, requestId: crypto.randomUUID() };
      }
      const pending = messageNode({ role: "user", text });
      messages.append(pending);
      messages.scrollTop = messages.scrollHeight;
      let next;
      try {
        next = await api(`${sessionPath(id)}/messages`, { text, request_id: retry.requestId });
      } catch (error) {
        if (!error.status || error.status === 409 || error.status >= 500) {
          const current = await api(sessionPath(id)).catch(() => null);
          if (current) {
            const answered = hasAnswer(current, retry.requestId);
            render(current);
            if (answered || current.session.processing) return;
          }
        }
        throw error;
      } finally {
        pending.remove();
      }
      select(next);
    });
  });

  run("Подключение к агенту…", async () => {
    sessions = await api("/sessions");
    let saved;
    try { saved = localStorage.getItem(storageKey); } catch { /* Optional browser preference. */ }
    const selected = sessions.find(({ id }) => id === saved) ?? sessions[0];
    select(selected ? await api(sessionPath(selected.id)) : await api("/sessions", {}));
  });
})();
