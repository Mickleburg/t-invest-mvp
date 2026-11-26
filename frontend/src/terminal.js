const byId = (id) => document.getElementById(id);

const marketRows = [
  ["GAZP", "9,64", "107,35", "+0,89%"],
  ["LKOH", "8,58", "5 858,00", "+1,66%"],
  ["SBER", "6,85", "289,66", "+0,51%"],
  ["OZON", "6,36", "3 614,50", "+3,79%"],
  ["VKCO", "5,21", "215,30", "+4,59%"],
  ["VTBR", "5,15", "56,37", "+1,29%"],
  ["T", "4,93", "280,32", "+0,58%"],
  ["NVTK", "3,49", "1 031,90", "+1,00%"],
  ["GMKN", "3,45", "112,36", "+2,89%"],
  ["PLZL", "3,08", "1 040,20", "+2,52%"],
  ["TATN", "2,62", "554,50", "−1,09%"],
  ["YDEX", "2,58", "3 282,00", "−0,27%"],
  ["ROSN", "2,20", "328,65", "−0,36%"],
  ["AFKS", "1,60", "7,958", "+0,48%"],
  ["ALRS", "1,46", "22,22", "+1,32%"],
  ["POSI", "1,43", "1 299,20", "+5,06%"],
  ["X5", "1,42", "2 336,50", "+2,01%"],
  ["SVCB", "1,11", "10,975", "+1,53%"],
  ["MAGN", "0,983", "21,09", "−0,40%"],
  ["CHMF", "0,908", "630,40", "−0,76%"],
  ["AFLT", "0,873", "35,43", "−0,78%"],
  ["MOEX", "0,821", "160,08", "+0,84%"],
  ["MTSS", "0,739", "174,15", "−0,68%"],
];

for (const [ticker, turnover, price, change] of marketRows) {
  const row = byId("market-rows").insertRow();
  row.classList.toggle("current", ticker === "SBER");
  const tickerCell = document.createElement("th");
  tickerCell.scope = "row";
  tickerCell.textContent = ticker;
  row.append(tickerCell);
  row.insertCell().textContent = turnover;
  row.insertCell().textContent = price;
  const changeCell = row.insertCell();
  changeCell.className = change.startsWith("+") ? "up" : "down";
  changeCell.textContent = change;
}

const tickerSearch = byId("ticker-search");
const tickerRows = [...byId("market-rows").rows];
tickerSearch.addEventListener("input", () => {
  const query = tickerSearch.value.trim().toUpperCase();
  for (const row of tickerRows) row.hidden = !row.cells[0].textContent.includes(query);
  byId("ticker-empty").hidden = tickerRows.some((row) => !row.hidden);
});

function observeChart(canvas, draw) {
  const context = canvas.getContext("2d");
  const render = () => {
    const { width, height } = canvas.getBoundingClientRect();
    if (!width || !height) return;
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    context.setTransform(scale, 0, 0, scale, 0, 0);
    draw(context, width, height);
  };
  new ResizeObserver(render).observe(canvas);
  return render;
}

const periods = {
  month: { candles: 6, labels: ["Окт", "Ноя"] },
  halfyear: { candles: 31, labels: ["Июн", "Авг", "Окт", "Ноя"] },
  all: { candles: 116, labels: ["Янв ’25", "Июн", "Янв ’26", "Июн", "Ноя"] },
};
let chartPeriod = "all";

// A fixed set of synthetic prices keeps the series consistent across periods.
const priceAnchors = [242, 260, 226, 254, 282, 278, 316, 309, 291, 317, 306,
  316, 299, 281, 291, 307, 300, 296, 312, 320, 313, 328, 315, 301, 249,
  273, 267, 279, 286, 289.66];
let previousClose = priceAnchors[0] - 2;
const priceSeries = Array.from({ length: periods.all.candles }, (_, i) => {
  const position = i * (priceAnchors.length - 1) / (periods.all.candles - 1);
  const base = Math.min(Math.floor(position), priceAnchors.length - 2);
  const jitter = (Math.sin(i * 2.75) + Math.cos(i * 6.41)) * 2.5;
  const open = previousClose;
  const close = i === periods.all.candles - 1 ? 289.66
    : priceAnchors[base] + (priceAnchors[base + 1] - priceAnchors[base]) * (position - base) + jitter;
  previousClose = close;
  return {
    open,
    close,
    high: Math.max(open, close) + 2 + Math.abs(jitter) * 0.5,
    low: Math.min(open, close) - 2 - Math.abs(jitter),
    volume: 3 + Math.abs(close - open) * 2 + Math.abs(jitter),
  };
});

function drawPriceChart(ctx, width, height) {
  const plotWidth = width - 47;
  const plotHeight = height - 5;
  if (plotWidth <= 0 || plotHeight <= 18) return;
  const candles = priceSeries.slice(-periods[chartPeriod].candles);
  const low = Math.min(...candles.map((candle) => candle.low));
  const high = Math.max(...candles.map((candle) => candle.high));
  const interval = high - low > 80 ? 20 : high - low > 30 ? 10 : 5;
  const lower = Math.floor(low / interval) * interval;
  const upper = Math.ceil(high / interval) * interval;
  const priceY = (price) => 8 + (upper - price) / (upper - lower) * (plotHeight - 16);
  ctx.font = "12px system-ui";
  ctx.textBaseline = "middle";
  ctx.strokeStyle = "#2a394e";
  ctx.fillStyle = "#a1afc2";
  for (let price = lower; price <= upper; price += interval) {
    const y = priceY(price);
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(plotWidth, y);
    ctx.stroke();
    ctx.fillText(String(price), plotWidth + 7, y);
  }
  for (let i = 1; i <= 5; i++) {
    const x = (plotWidth / 5) * i;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, plotHeight);
    ctx.stroke();
  }

  const step = plotWidth / candles.length;
  const candleWidth = clamp(step * 0.64, 1, 16);
  for (const [i, { open, close, high, low, volume }] of candles.entries()) {
    const x = (i + 0.5) * step;
    const color = close >= open ? "#57c9a1" : "#e08194";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, priceY(high));
    ctx.lineTo(x, priceY(low));
    ctx.stroke();
    ctx.fillRect(x - candleWidth / 2, priceY(Math.max(open, close)), candleWidth,
      Math.max(1.2, Math.abs(priceY(open) - priceY(close))));
    const volumeHeight = Math.min(plotHeight * 0.18, volume);
    ctx.globalAlpha = 0.27;
    ctx.fillRect(x - candleWidth / 2, plotHeight - volumeHeight, candleWidth, volumeHeight);
    ctx.globalAlpha = 1;
  }

  const lastY = priceY(289.66);
  ctx.setLineDash([3, 4]);
  ctx.strokeStyle = "#65dcb2";
  ctx.beginPath();
  ctx.moveTo(0, lastY);
  ctx.lineTo(plotWidth, lastY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#285447";
  ctx.fillRect(plotWidth, lastY - 9, 47, 18);
  ctx.fillStyle = "#b7fbe4";
  ctx.fillText("289,66", plotWidth + 4, lastY);
}

function drawDepthChart(ctx, width, height) {
  const levels = [0.1, 0.29, 0.29, 0.49, 0.49, 0.64, 0.68, 0.78,
    0.82, 0.88, 0.94, 0.98, 0.92, 0.88, 0.82, 0.79, 0.69, 0.65, 0.48,
    0.48, 0.31, 0.3, 0.1];
  const gradient = ctx.createLinearGradient(0, 0, width, 0);
  gradient.addColorStop(0, "#61c6a4");
  gradient.addColorStop(0.5, "#758da4");
  gradient.addColorStop(1, "#dc8590");
  ctx.beginPath();
  ctx.moveTo(0, 20 + levels[0] * (height - 23));
  for (let i = 1; i < levels.length; i++) {
    const y = 20 + levels[i] * (height - 23);
    const x = width * i / (levels.length - 1);
    ctx.lineTo(x, 20 + levels[i - 1] * (height - 23));
    ctx.lineTo(x, y);
  }
  ctx.strokeStyle = gradient;
  ctx.lineWidth = 1.6;
  ctx.stroke();
  ctx.lineTo(width, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.globalAlpha = 0.13;
  ctx.fill();
  ctx.globalAlpha = 1;
}

const renderPriceChart = observeChart(byId("price-chart"), drawPriceChart);
observeChart(byId("depth-chart"), drawDepthChart);

const periodButtons = [...byId("chart-periods").querySelectorAll("button")];
const chartAxis = document.querySelector(".chart-axis");
for (const button of periodButtons) {
  button.addEventListener("click", () => {
    chartPeriod = button.dataset.period;
    for (const option of periodButtons) option.setAttribute("aria-pressed", String(option === button));
    chartAxis.replaceChildren(...periods[chartPeriod].labels.map((label) => {
      const tick = document.createElement("span");
      tick.textContent = label;
      return tick;
    }));
    renderPriceChart();
  });
}

const widget = byId("tradeguard-window");
const widgetBar = byId("widget-bar");
const widgetContent = byId("widget-content");
const widgetDock = document.querySelector(".widget-dock");
const workbench = document.querySelector(".workbench");
const terminal = document.querySelector(".terminal");
const panels = [...terminal.querySelectorAll(".panel")];
const windows = [...panels, widget];
const windowPickerButton = byId("show-windows");
const windowPicker = byId("window-picker");
const toggle = byId("toggle-widget");
const minimize = byId("minimize-widget");
const maximize = byId("maximize-widget");
const grip = byId("resize-widget");
const docked = window.matchMedia("(min-width: 1081px)");
const titleHeight = 38;
const minimumWidth = 278;
const minimumHeight = 334;
const minimumPanelWidth = 136;
const minimumPanelHeight = 160;
const resizeEdges = ["top", "right", "bottom", "left", "top-left", "top-right", "bottom-left", "bottom-right"];
const clamp = (value, min, max) => Math.max(min, Math.min(value, max));

let collapsed = !docked.matches;
let maximized = false;
let manualBounds;
let topWindow = widget;
let topLayer = 2;
const origin = { x: 0, y: 0 };
const panelLayouts = new Map();
const windowToggles = new Map();

function bringToFront(panel) {
  if (topWindow === panel) return;
  topWindow = panel;
  panel.style.zIndex = String(++topLayer);
}

function workspaceBounds() {
  const board = workbench.getBoundingClientRect();
  const { left, top } = terminal.getBoundingClientRect();
  const padding = left - board.left;
  return { left, top, right: board.right - padding, bottom: board.bottom - padding };
}

function viewportBounds() {
  const workspace = workspaceBounds();
  const bottom = Math.min(workspace.bottom, window.innerHeight - workspace.left);
  return {
    left: workspace.left,
    top: clamp(workspace.top, workspace.left, bottom - titleHeight),
    right: workspace.right,
    bottom,
  };
}

function getGeometry() {
  const viewport = viewportBounds();
  const areaWidth = viewport.right - viewport.left;
  const areaHeight = viewport.bottom - viewport.top;
  if (maximized && !collapsed) {
    return { x: viewport.left, y: viewport.top, width: areaWidth, height: areaHeight };
  }
  const dock = widgetDock.getBoundingClientRect();
  const width = docked.matches ? dock.width : Math.min(390, areaWidth);
  const height = docked.matches ? terminal.getBoundingClientRect().height : 590;
  const initialBounds = {
    x: viewport.right - width,
    y: !docked.matches && collapsed ? viewport.bottom - titleHeight : viewport.top,
    width,
    height,
  };
  const normal = manualBounds ?? initialBounds;
  const fittedWidth = clamp(normal.width, Math.min(minimumWidth, areaWidth), areaWidth);
  const fittedHeight = clamp(normal.height, Math.min(minimumHeight, areaHeight), areaHeight);
  return {
    x: clamp(normal.x, viewport.left, viewport.right - fittedWidth),
    y: clamp(normal.y, viewport.top, viewport.bottom - (collapsed ? titleHeight : fittedHeight)),
    width: fittedWidth,
    height: fittedHeight,
  };
}

function updateGeometry() {
  const { x, y, width, height } = getGeometry();
  widget.style.left = `${x}px`;
  widget.style.top = `${y}px`;
  widget.style.width = `${width}px`;
  widget.style.height = `${collapsed ? titleHeight : height}px`;
}

function updateWindow() {
  widgetContent.hidden = collapsed;
  widget.classList.toggle("is-collapsed", collapsed);
  widget.classList.toggle("is-resizable", !collapsed && !maximized);
  grip.hidden = collapsed || maximized;
  toggle.setAttribute("aria-expanded", String(!widget.hidden && !collapsed));
  minimize.setAttribute("aria-expanded", String(!collapsed));
  minimize.title = collapsed ? "Восстановить окно" : "Свернуть окно";
  minimize.setAttribute("aria-label", minimize.title);
  minimize.textContent = collapsed ? "+" : "−";
  maximize.title = maximized && !collapsed ? "Вернуть размер окна" : "Развернуть окно";
  maximize.setAttribute("aria-label", maximize.title);
  maximize.textContent = maximized && !collapsed ? "❐" : "□";
  updateGeometry();
}

function toggleCollapsed() {
  bringToFront(widget);
  if (widget.hidden) {
    collapsed = false;
    setWindowVisibility(widget, true);
    return;
  }
  collapsed = !collapsed;
  updateWindow();
}

toggle.addEventListener("click", toggleCollapsed);
minimize.addEventListener("click", toggleCollapsed);
maximize.addEventListener("click", () => {
  maximized = collapsed || !maximized;
  collapsed = false;
  updateWindow();
});
window.addEventListener("scroll", updateGeometry, { passive: true });
updateWindow();

function moveWindow(start, dx, dy) {
  maximized = false;
  manualBounds = { ...start, x: start.x + dx, y: start.y + dy };
  updateGeometry();
}

function resizeWindow(edge, start, dx, dy) {
  manualBounds = resizeFromEdges(edge, start, dx, dy, viewportBounds(), minimumWidth, minimumHeight);
  updateGeometry();
}

function resizeFromEdges(edge, start, dx, dy, bounds, minimumWidth, minimumHeight) {
  const minWidth = Math.min(start.width, minimumWidth);
  const minHeight = Math.min(start.height, minimumHeight);
  let left = start.x;
  let top = start.y;
  let right = left + start.width;
  let bottom = top + start.height;

  if (edge.includes("left")) left = clamp(left + dx, bounds.left, right - minWidth);
  if (edge.includes("right")) right = clamp(right + dx, left + minWidth, bounds.right);
  if (edge.includes("top")) top = clamp(top + dy, bounds.top, bottom - minHeight);
  if (edge.includes("bottom")) bottom = clamp(bottom + dy, top + minHeight, bounds.bottom);

  return { x: left, y: top, width: right - left, height: bottom - top };
}

function bindWindowGesture(handle, panel, read, apply, disabled = () => false) {
  let gesture;
  handle.addEventListener("pointerdown", (event) => {
    if (disabled() || !event.isPrimary || event.button !== 0) return;
    if (event.target !== handle && event.target.closest("button")) return;
    event.preventDefault();
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, start: read() };
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", (event) => {
    if (!gesture || gesture.id !== event.pointerId) return;
    const dx = event.clientX - gesture.x;
    const dy = event.clientY - gesture.y;
    panel.classList.add("is-moving");
    apply(gesture.start, dx, dy);
  });
  handle.addEventListener("lostpointercapture", () => {
    gesture = undefined;
    panel.classList.remove("is-moving");
  });
  handle.addEventListener("keydown", (event) => {
    if (disabled() || event.target !== handle) return;
    const offsets = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const offset = offsets[event.key];
    if (!offset) return;
    event.preventDefault();
    bringToFront(panel);
    const step = event.shiftKey ? 32 : 8;
    apply(read(), offset[0] * step, offset[1] * step);
  });
}

function bindResizeHandles(panel, grip, read, resize, disabled) {
  for (const edge of resizeEdges) {
    const handle = edge === "bottom-right" ? grip : document.createElement("span");
    handle.dataset.resizeEdge = edge;
    if (handle !== grip) {
      handle.className = "resize-edge";
      handle.setAttribute("aria-hidden", "true");
      panel.append(handle);
    }
    bindWindowGesture(handle, panel, read, (start, dx, dy) => resize(edge, start, dx, dy), disabled);
  }
}

function positionPanel(panel, requested) {
  const current = panelLayouts.get(panel) ?? origin;
  const rect = panel.getBoundingClientRect();
  const bounds = workspaceBounds();
  const left = rect.left - current.x;
  const top = rect.top - current.y;
  const width = requested.width === undefined ? undefined : Math.min(requested.width, bounds.right - bounds.left);
  const height = requested.height === undefined ? undefined : Math.min(requested.height, bounds.bottom - bounds.top);
  const x = clamp(requested.x, bounds.left - left, bounds.right - left - (width ?? rect.width));
  const y = clamp(requested.y, bounds.top - top, bounds.bottom - top - (height ?? rect.height));
  if (width !== undefined) panel.style.width = `${width}px`;
  if (height !== undefined) panel.style.height = `${height}px`;
  panel.style.translate = `${x}px ${y}px`;
  panelLayouts.set(panel, { x, y, width, height });
}

function setWindowVisibility(panel, visible) {
  panel.hidden = !visible;
  windowToggles.get(panel).checked = visible;
  if (panel === widget) {
    updateWindow();
  } else if (visible && panelLayouts.has(panel)) {
    positionPanel(panel, panelLayouts.get(panel));
  }
}

function positionWindowPicker() {
  const trigger = windowPickerButton.getBoundingClientRect();
  windowPicker.style.setProperty("--picker-top", `${Math.max(8, trigger.bottom + 5)}px`);
  windowPicker.style.setProperty("--picker-anchor", `${trigger.right}px`);
}

windowPicker.addEventListener("beforetoggle", (event) => {
  if (event.newState === "open") positionWindowPicker();
});
window.addEventListener("scroll", () => {
  if (windowPicker.matches(":popover-open")) positionWindowPicker();
}, { passive: true });

for (const panel of windows) {
  const titleId = panel.getAttribute("aria-labelledby");
  const title = byId(titleId).textContent;
  if (!panel.id) panel.id = `${titleId.replace(/-title$/, "")}-window`;

  const label = document.createElement("label");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = true;
  checkbox.setAttribute("aria-controls", panel.id);
  checkbox.addEventListener("change", () => {
    setWindowVisibility(panel, checkbox.checked);
    if (checkbox.checked) bringToFront(panel);
  });
  label.append(checkbox, title);
  windowPicker.append(label);
  windowToggles.set(panel, checkbox);

  const close = panel.querySelector(".window-close");
  close.addEventListener("click", () => {
    setWindowVisibility(panel, false);
    windowPickerButton.focus({ preventScroll: true });
  });
}

for (const panel of panels) {
  const readLayout = () => panelLayouts.get(panel) ?? origin;
  const move = (start, dx, dy) => positionPanel(panel, { ...start, x: start.x + dx, y: start.y + dy });
  bindWindowGesture(panel.querySelector(".drag-handle"), panel, readLayout, move);

  const resizeGrip = document.createElement("button");
  const title = document.getElementById(panel.getAttribute("aria-labelledby")).textContent;
  resizeGrip.type = "button";
  resizeGrip.className = "resize-grip";
  resizeGrip.title = "Изменить размер за край или угол окна";
  resizeGrip.setAttribute("aria-label", `Изменить размер окна «${title}» клавишами со стрелками`);
  panel.append(resizeGrip);
  const readSize = () => {
    const { x, y, width, height } = panel.getBoundingClientRect();
    return { x, y, width, height };
  };
  const resize = (edge, start, dx, dy) => {
    const { left, top } = panel.getBoundingClientRect();
    const layout = readLayout();
    const box = resizeFromEdges(edge, start, dx, dy, workspaceBounds(), minimumPanelWidth, minimumPanelHeight);
    positionPanel(panel, { ...box, x: layout.x + box.x - left, y: layout.y + box.y - top });
  };
  bindResizeHandles(panel, resizeGrip, readSize, resize);
}
bindWindowGesture(widgetBar, widget, getGeometry, moveWindow, () => maximized && !collapsed);
bindResizeHandles(widget, grip, getGeometry, resizeWindow, () => collapsed || maximized);

workbench.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  const panel = event.target.closest(".panel, .widget");
  if (panel) bringToFront(panel);
});
window.addEventListener("resize", () => {
  for (const [panel, layout] of panelLayouts) {
    if (!panel.hidden) positionPanel(panel, layout);
  }
  if (windowPicker.matches(":popover-open")) positionWindowPicker();
  updateGeometry();
});
byId("reset-layout").addEventListener("click", () => {
  panelLayouts.clear();
  for (const panel of panels) {
    panel.style.removeProperty("translate");
    panel.style.removeProperty("z-index");
    panel.style.removeProperty("width");
    panel.style.removeProperty("height");
    setWindowVisibility(panel, true);
  }
  widget.style.removeProperty("z-index");
  topWindow = widget;
  topLayer = 2;
  manualBounds = undefined;
  collapsed = !docked.matches;
  maximized = false;
  setWindowVisibility(widget, true);
});

const tabs = [...document.querySelectorAll(".widget-tabs button")];
function showView(view) {
  widgetContent.dataset.view = view;
  for (const tab of tabs) tab.setAttribute("aria-pressed", String(tab.dataset.view === view));
}

for (const tab of tabs) tab.addEventListener("click", () => showView(tab.dataset.view));
const practiceOrder = byId("practice-order");
const practiceSymbol = byId("practice-symbol");
const practiceSide = byId("practice-side");
const practiceStatus = byId("practice-status");
const practiceQuotes = {
  SBER: ["289,66 ₽", "Лот: 10 акций"],
  SiZ6: ["85 000 ₽", "Лот: 1 контракт"],
};

function updatePracticeOrder() {
  const [price, lot] = practiceQuotes[practiceSymbol.value];
  byId("practice-price").textContent = price;
  byId("practice-lot").textContent = lot;
  byId("practice-submit").textContent = practiceSide.selectedIndex === 0 ? "Купить" : "Продать";
  practiceStatus.hidden = true;
}
practiceOrder.addEventListener("input", updatePracticeOrder);
for (const action of document.querySelectorAll(".order-actions button")) {
  action.addEventListener("click", () => {
    bringToFront(widget);
    collapsed = false;
    showView("order");
    practiceSymbol.value = "SBER";
    practiceSide.value = action.dataset.side;
    updatePracticeOrder();
    setWindowVisibility(widget, true);
    practiceSymbol.focus();
  });
}
practiceOrder.addEventListener("submit", (event) => {
  event.preventDefault();
  const quantity = byId("practice-quantity").value;
  practiceStatus.textContent = `Черновик · ${practiceSide.value.toLowerCase()}, ${practiceSymbol.value}, лотов: ${quantity}`;
  practiceStatus.hidden = false;
});
