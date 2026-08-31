import {
  escapeHtml,
  fetchJson,
  formatDate,
  formatMetric,
  formatTime,
  shortId,
  shortMetric,
} from "/static/shared.js";

const SNAPSHOT_INTERVAL_MS = 10000;
const REALTIME_INTERVAL_MS = 2000;
const TIMESERIES_INTERVAL_MS = 10000;

const state = {
  snapshot: null,
  series: new Map(),
  rangeSeconds: 300,
  autoRefresh: true,
  selectedRun: null,
  timers: [],
  loading: new Set(),
};

const serviceNames = {
  api: "API",
  prometheus: "Prometheus",
  loki: "Loki",
  otel: "OpenTelemetry",
  tempo: "Tempo",
  langfuse: "Langfuse",
  agno: "Runtime Agno",
  locust: "Locust",
};

const realtimeKeys = new Set([
  "req_user",
  "http_5xx",
  "queue",
  "jobs_active",
  "cpu",
  "ram",
  "llm_calls_per_min",
  "agno_calls_per_min",
]);

const chartConfigs = {
  requests: {
    unit: "rps",
    keys: [
      { key: "req_user", label: "Usuários", color: "#166534" },
      { key: "req_internal", label: "Interno", color: "#b45309" },
      { key: "req_total", label: "Total", color: "#1d4ed8" },
    ],
  },
  http: {
    unit: "percent",
    keys: [
      { key: "http_4xx", label: "4xx", color: "#b45309" },
      { key: "http_5xx", label: "5xx", color: "#b91c1c" },
    ],
  },
  pipeline: {
    unit: "count",
    keys: [
      { key: "queue", label: "Fila", color: "#b45309" },
      { key: "jobs_active", label: "Ativos", color: "#166534" },
    ],
  },
  pipeline_rate: {
    unit: "per_minute",
    keys: [
      { key: "jobs_done_per_min", label: "Concluídos", color: "#166534" },
      { key: "jobs_error_per_min", label: "Erros", color: "#b91c1c" },
    ],
  },
  outputs: {
    unit: "per_minute",
    keys: [
      { key: "exports_per_min", label: "Exportações", color: "#1d4ed8" },
      { key: "pipeline_errors_per_min", label: "Falhas", color: "#b91c1c" },
    ],
  },
  infra: {
    unit: "percent",
    keys: [
      { key: "cpu", label: "CPU", color: "#1d4ed8" },
      { key: "ram", label: "RAM", color: "#166534" },
      { key: "disk_root", label: "Disco", color: "#b45309" },
    ],
  },
  network: {
    unit: "bytes_per_second",
    keys: [
      { key: "net_rx", label: "Entrada", color: "#166534" },
      { key: "net_tx", label: "Saída", color: "#1d4ed8" },
    ],
  },
  llm_calls: {
    unit: "per_minute",
    keys: [
      { key: "llm_calls_per_min", label: "Pipeline", color: "#1d4ed8" },
      { key: "llm_failures_per_min", label: "Falhas", color: "#b91c1c" },
      { key: "agno_calls_per_min", label: "Console Agno", color: "#166534" },
    ],
  },
  llm_latency: {
    unit: "seconds",
    keys: [
      { key: "llm_duration_avg", label: "Pipeline", color: "#1d4ed8" },
      { key: "llm_ttft_avg", label: "TTFT pipeline", color: "#b45309" },
      { key: "agno_duration_avg", label: "Console Agno", color: "#166534" },
      { key: "agno_ttft_avg", label: "TTFT Agno", color: "#7c3aed" },
    ],
  },
  llm_tokens: {
    unit: "tokens_per_second",
    keys: [
      { key: "llm_input_tokens_rate", label: "Input", color: "#1d4ed8" },
      { key: "llm_output_tokens_rate", label: "Output", color: "#166534" },
      { key: "llm_reasoning_tokens_rate", label: "Reasoning", color: "#b45309" },
    ],
  },
};

const dom = {
  updatedAt: document.getElementById("updated-at"),
  overallStatus: document.getElementById("overall-status"),
  connectionNotice: document.getElementById("connection-notice"),
  realtimeUpdated: document.getElementById("realtime-updated"),
  realtimeMetrics: document.getElementById("realtime-metrics"),
  apiHealth: document.getElementById("api-health"),
  historyBody: document.getElementById("history-body"),
  runSearch: document.getElementById("run-search"),
  runStatus: document.getElementById("run-status"),
  runsBody: document.getElementById("runs-body"),
  runDetail: document.getElementById("run-detail"),
  logsSearch: document.getElementById("logs-search"),
  logsState: document.getElementById("logs-state"),
  logList: document.getElementById("log-list"),
  annotationForm: document.getElementById("annotation-form"),
  annotationList: document.getElementById("annotation-list"),
  autoRefresh: document.getElementById("auto-refresh"),
  refreshButton: document.getElementById("refresh-all"),
};

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});

document.querySelectorAll("[data-range]").forEach((button) => {
  button.addEventListener("click", () => {
    state.rangeSeconds = Number(button.dataset.range);
    document.querySelectorAll("[data-range]").forEach((item) => {
      item.classList.toggle("active", item === button);
      item.setAttribute("aria-pressed", item === button ? "true" : "false");
    });
    loadTimeseries();
  });
});

dom.autoRefresh.addEventListener("change", () => {
  state.autoRefresh = dom.autoRefresh.checked;
  configureTimers();
});
dom.refreshButton.addEventListener("click", refreshAll);
document.getElementById("runs-filter").addEventListener("submit", (event) => {
  event.preventDefault();
  loadRuns();
});
document.getElementById("logs-filter").addEventListener("submit", (event) => {
  event.preventDefault();
  loadLogs();
});
dom.annotationForm.addEventListener("submit", createAnnotation);

function activateTab(tabId) {
  const selected = document.querySelector(`[data-tab="${tabId}"]`);
  if (!selected) return;
  document.querySelectorAll("[data-tab]").forEach((item) => {
    const active = item === selected;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".workspace-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === tabId);
  });
  window.history.replaceState(null, "", `#${tabId}`);
  drawCharts();
}

async function refreshAll() {
  dom.refreshButton.disabled = true;
  await Promise.allSettled([
    loadSnapshot(),
    loadRealtime(),
    loadTimeseries(),
    loadRuns(),
  ]);
  dom.refreshButton.disabled = false;
}

async function loadSnapshot() {
  if (state.loading.has("snapshot")) return;
  state.loading.add("snapshot");
  try {
    const payload = await fetchJson("/api/snapshot");
    state.snapshot = payload;
    renderSnapshot(payload);
    setConnectionState(true);
  } catch (error) {
    setConnectionState(false, error.message);
  } finally {
    state.loading.delete("snapshot");
  }
}

async function loadRealtime() {
  if (state.loading.has("realtime")) return;
  state.loading.add("realtime");
  try {
    const payload = await fetchJson("/api/realtime");
    appendRealtime(payload.metrics || [], payload.generated_at);
    renderRealtime(payload.metrics || [], payload.generated_at);
    drawCharts();
  } catch (error) {
    dom.realtimeUpdated.textContent = "Tempo real indisponível";
    dom.realtimeUpdated.title = error.message;
  } finally {
    state.loading.delete("realtime");
  }
}

async function loadTimeseries() {
  if (state.loading.has("timeseries")) return;
  state.loading.add("timeseries");
  const step = Math.max(1, Math.round(state.rangeSeconds / 300));
  try {
    const payload = await fetchJson(
      `/api/timeseries?range_seconds=${state.rangeSeconds}&step_seconds=${step}`,
    );
    replaceSeries(payload.series || []);
    drawCharts();
  } finally {
    state.loading.delete("timeseries");
  }
}

async function loadRuns() {
  if (state.loading.has("runs")) return;
  state.loading.add("runs");
  const params = new URLSearchParams({
    search: dom.runSearch.value.trim(),
    status: dom.runStatus.value,
    limit: "100",
  });
  try {
    const payload = await fetchJson(`/api/investigations/runs?${params}`);
    renderRuns(payload.items || []);
  } catch (error) {
    dom.runsBody.innerHTML = `<tr><td colspan="8" class="empty-cell">${escapeHtml(error.message)}</td></tr>`;
  } finally {
    state.loading.delete("runs");
  }
}

async function loadRunDetails(runId) {
  dom.runDetail.innerHTML = '<div class="empty-state">Carregando execução...</div>';
  try {
    const details = await fetchJson(`/api/investigations/runs/${encodeURIComponent(runId)}`);
    state.selectedRun = details;
    renderRunDetails(details);
  } catch (error) {
    dom.runDetail.innerHTML = `<div class="empty-state error-text">${escapeHtml(error.message)}</div>`;
  }
}

async function loadLogs(search = dom.logsSearch.value.trim()) {
  dom.logsSearch.value = search;
  dom.logsState.textContent = "Consultando...";
  const params = new URLSearchParams({ search, limit: "150" });
  try {
    const payload = await fetchJson(`/api/logs?${params}`);
    renderLogs(payload.entries || [], payload);
  } catch (error) {
    dom.logsState.textContent = "Consulta indisponível";
    dom.logList.innerHTML = `<div class="empty-state error-text">${escapeHtml(error.message)}</div>`;
  }
}

function renderSnapshot(snapshot) {
  renderServices(snapshot.service_details || {});
  renderGroups(snapshot.metrics || {});
  renderApi(snapshot.api || {});
  renderHistory(snapshot.api?.history || []);
  renderLogs(snapshot.logs || [], snapshot.sources?.logs || {});
  renderAnnotations(snapshot.annotations || []);
  dom.updatedAt.textContent = `Atualizado ${formatTime(snapshot.generated_at)}`;
}

function renderServices(details) {
  const states = Object.values(details).map((detail) => detail.state || "offline");
  const online = states.filter((value) => value === "online").length;
  const degraded = states.filter((value) => value === "degraded").length;
  dom.overallStatus.className = `overall-status ${degraded ? "degraded" : online === states.length ? "online" : "offline"}`;
  dom.overallStatus.textContent = `${online} de ${states.length} online${degraded ? `, ${degraded} degradado` : ""}`;

  document.querySelectorAll("[data-service]").forEach((item) => {
    const key = item.dataset.service;
    const detail = details[key] || { state: "offline", available: false };
    const serviceState = detail.state || (detail.available ? "online" : "offline");
    item.classList.remove("online", "degraded", "offline", "empty");
    item.classList.add(serviceState);
    item.querySelector(".service-state").textContent = serviceStateLabel(serviceState);
    item.title = detail.error || detail.endpoint || serviceNames[key] || key;
  });
}

function serviceStateLabel(value) {
  return {
    online: "online",
    degraded: "degradado",
    empty: "sem dados",
    offline: "offline",
  }[value] || value;
}

function renderGroups(groups) {
  document.querySelectorAll("[data-group]").forEach((container) => {
    const metrics = groups[container.dataset.group] || [];
    container.replaceChildren(...metrics.map(metricCard));
  });
}

function metricCard(metric) {
  const article = document.createElement("article");
  article.className = `metric-card metric-${metric.state || "empty"}`;
  const label = document.createElement("span");
  label.className = "metric-label";
  label.textContent = metric.label;
  const value = document.createElement("strong");
  value.className = "metric-value";

  if (metric.items?.length) {
    value.textContent = `${metric.items.length} séries`;
    const list = document.createElement("div");
    list.className = "metric-breakdown";
    metric.items.slice(0, 8).forEach((item) => {
      const row = document.createElement("div");
      const itemLabel = document.createElement("span");
      itemLabel.textContent = item.label;
      const itemValue = document.createElement("strong");
      itemValue.textContent = formatMetric(item.value, metric.unit);
      row.append(itemLabel, itemValue);
      list.appendChild(row);
    });
    article.append(label, value, list);
    return article;
  }

  value.textContent = metricStateValue(metric);
  article.title = metric.error || "";
  article.append(label, value);
  return article;
}

function metricStateValue(metric) {
  if (metric.state === "error") return "consulta falhou";
  if (metric.state === "unavailable") return "fonte offline";
  return formatMetric(metric.value, metric.unit);
}

function renderRealtime(metrics, generatedAt) {
  const visible = metrics.filter((metric) => realtimeKeys.has(metric.key));
  dom.realtimeMetrics.replaceChildren(...visible.map((metric) => {
    const card = document.createElement("article");
    card.className = `live-metric metric-${metric.state || "empty"}`;
    const label = document.createElement("span");
    label.textContent = metric.label;
    const value = document.createElement("strong");
    value.textContent = metricStateValue(metric);
    card.append(label, value);
    return card;
  }));
  dom.realtimeUpdated.textContent = `Tempo real ${formatTime(generatedAt)}`;
}

function appendRealtime(metrics, generatedAt) {
  const timestamp = generatedAt ? new Date(generatedAt).getTime() / 1000 : Date.now() / 1000;
  metrics.forEach((metric) => {
    if (!metric.key || metric.value === null || metric.value === undefined) return;
    const value = Number(metric.value);
    if (!Number.isFinite(value)) return;
    const current = state.series.get(metric.key) || [];
    current.push({ time: timestamp, value });
    state.series.set(
      metric.key,
      current.filter((point) => point.time >= timestamp - state.rangeSeconds),
    );
  });
}

function replaceSeries(series) {
  series.forEach((item) => {
    if (!item.key) return;
    const points = (item.points || [])
      .map((point) => ({ time: Number(point.time), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
    state.series.set(item.key, points);
  });
}

function renderApi(api) {
  const health = api.health || {};
  const stats = api.stats || {};
  const facts = [
    ["Status", health.status || "sem dado"],
    ["Modelo", health.model_name || "sem dado"],
    ["Cliente", health.model_client || "sem dado"],
    ["Modelo acessível", health.model_reachable ? "sim" : "não"],
    ["Fila", health.queue_size ?? "sem dado"],
    ["Conversões", stats.total ?? "sem dado"],
    ["Sucessos", stats.sucesso ?? "sem dado"],
    ["Erros", stats.erros ?? "sem dado"],
    ["Tempo médio", stats.tempo_medio_segundos == null ? "sem dado" : `${stats.tempo_medio_segundos}s`],
  ];
  dom.apiHealth.replaceChildren(...facts.map(([key, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = key;
    const definition = document.createElement("dd");
    definition.textContent = String(value);
    row.append(term, definition);
    return row;
  }));
}

function renderHistory(rows) {
  if (!rows.length) {
    dom.historyBody.innerHTML = '<tr><td colspan="4" class="empty-cell">Sem histórico recente.</td></tr>';
    return;
  }
  dom.historyBody.innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.arquivo || "-")}</td>
      <td><span class="status-badge">${escapeHtml(row.status || "-")}</span></td>
      <td>${escapeHtml(row.modo || "-")}</td>
      <td>${formatMetric(row.tempo_segundos, "seconds")}</td>
    </tr>
  `).join("");
}

function renderRuns(items) {
  if (!items.length) {
    dom.runsBody.innerHTML = '<tr><td colspan="8" class="empty-cell">Nenhuma execução encontrada.</td></tr>';
    return;
  }
  dom.runsBody.innerHTML = items.map((run) => `
    <tr class="clickable-row" data-run-id="${escapeHtml(run.run_id)}" tabindex="0">
      <td>${formatDate(run.created_at, { dateStyle: "short", timeStyle: "medium" })}</td>
      <td><span class="status-badge status-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span></td>
      <td>${escapeHtml(run.entity_id)}</td>
      <td>${escapeHtml(run.model || "padrão")}</td>
      <td>${formatMetric(run.duration_seconds, "seconds")}</td>
      <td>${formatMetric(run.total_tokens, "tokens")}</td>
      <td><code title="${escapeHtml(run.trace_id)}">${escapeHtml(shortId(run.trace_id))}</code></td>
      <td>${run.event_count || 0} / ${run.tool_count || 0}</td>
    </tr>
  `).join("");
  dom.runsBody.querySelectorAll("[data-run-id]").forEach((row) => {
    const open = () => loadRunDetails(row.dataset.runId);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") open();
    });
  });
}

function renderRunDetails(details) {
  const run = details.run;
  const events = details.events || [];
  const tools = details.tools || [];
  const agnoUrl = `/agno?entity_id=${encodeURIComponent(run.entity_id)}&session_id=${encodeURIComponent(run.session_id)}`;
  dom.runDetail.innerHTML = `
    <div class="section-heading compact">
      <div>
        <span class="section-kicker">${escapeHtml(run.entity_type)}</span>
        <h3>${escapeHtml(run.entity_id)}</h3>
      </div>
      <span class="status-badge status-${escapeHtml(run.status)}">${escapeHtml(run.status)}</span>
    </div>
    <dl class="detail-list">
      <div><dt>Trace ID</dt><dd><code>${escapeHtml(run.trace_id || "-")}</code></dd></div>
      <div><dt>Run ID</dt><dd><code>${escapeHtml(run.run_id)}</code></dd></div>
      <div><dt>Session ID</dt><dd><code>${escapeHtml(run.session_id)}</code></dd></div>
      <div><dt>Modelo</dt><dd>${escapeHtml(run.model || "padrão")}</dd></div>
      <div><dt>Duração</dt><dd>${formatMetric(run.duration_seconds, "seconds")}</dd></div>
      <div><dt>TTFT</dt><dd>${formatMetric(run.ttft_seconds, "seconds")}</dd></div>
      <div><dt>Tokens</dt><dd>${formatMetric(run.total_tokens, "tokens")}</dd></div>
      <div><dt>Custo</dt><dd>${formatMetric(run.cost, "currency")}</dd></div>
    </dl>
    ${run.error ? `<div class="inline-error">${escapeHtml(run.error)}</div>` : ""}
    <div class="command-row">
      <a class="button primary" href="${agnoUrl}">Abrir sessão</a>
      <button class="button" type="button" id="filter-run-logs">Filtrar logs</button>
    </div>
    <div class="run-events-summary">
      <strong>${events.length} eventos</strong>
      <strong>${tools.length} ferramentas</strong>
    </div>
    <div class="event-timeline">
      ${events.slice(0, 40).map((event) => `
        <div><span class="timeline-dot"></span><strong>${escapeHtml(event.event_name)}</strong><time>${formatTime(event.created_at)}</time></div>
      `).join("") || '<div class="empty-state">Sem eventos registrados.</div>'}
    </div>
  `;
  document.getElementById("filter-run-logs")?.addEventListener("click", () => {
    activateTab("logs");
    loadLogs(run.trace_id || run.run_id);
  });
}

function renderLogs(logs, source = {}) {
  const available = source.query_available ?? source.state !== "degraded";
  dom.logsState.className = `source-state ${available ? "online" : "degraded"}`;
  dom.logsState.textContent = !source.available && source.available !== undefined
    ? "Loki offline"
    : available
    ? `${logs.length} entradas`
    : "Consulta degradada";
  dom.logsState.title = source.error || "";
  if (!logs.length) {
    dom.logList.innerHTML = '<div class="empty-state">Nenhum log no intervalo ou filtro atual.</div>';
    return;
  }
  dom.logList.innerHTML = logs.map((entry) => `
    <article class="log-entry">
      <div class="log-meta">
        <time>${formatDate(entry.time)}</time>
        <span class="log-level level-${escapeHtml(String(entry.level || "log").toLowerCase())}">${escapeHtml(entry.level || entry.format || "log")}</span>
        ${entry.module ? `<span>${escapeHtml(entry.module)}</span>` : ""}
        ${entry.trace_id ? `<code>${escapeHtml(shortId(entry.trace_id))}</code>` : ""}
      </div>
      <pre>${escapeHtml(entry.line || "")}</pre>
    </article>
  `).join("");
}

async function createAnnotation(event) {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(dom.annotationForm).entries());
  const submit = dom.annotationForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await fetchJson("/api/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    dom.annotationForm.note.value = "";
    await loadSnapshot();
  } finally {
    submit.disabled = false;
  }
}

function renderAnnotations(items) {
  if (!items.length) {
    dom.annotationList.innerHTML = '<div class="empty-state">Nenhuma anotação registrada.</div>';
    return;
  }
  dom.annotationList.innerHTML = items.map((item) => `
    <article class="annotation-item">
      <div class="annotation-heading">
        <strong>${escapeHtml(item.target_id)}</strong>
        <span class="status-badge severity-${escapeHtml(item.severity)}">${escapeHtml(item.severity)}</span>
      </div>
      <p>${escapeHtml(item.note)}</p>
      <footer>
        <span>${escapeHtml(item.target_type)}</span>
        <span>${escapeHtml(item.tags || "sem tags")}</span>
        <time>${formatDate(item.created_at)}</time>
        <button type="button" data-delete-annotation="${item.id}">Remover</button>
      </footer>
    </article>
  `).join("");
  dom.annotationList.querySelectorAll("[data-delete-annotation]").forEach((button) => {
    button.addEventListener("click", async () => {
      button.disabled = true;
      await fetchJson(`/api/annotations/${button.dataset.deleteAnnotation}`, { method: "DELETE" });
      await loadSnapshot();
    });
  });
}

function setConnectionState(connected, message = "") {
  dom.connectionNotice.hidden = connected;
  dom.connectionNotice.textContent = connected ? "" : `Painel sem conexão: ${message}`;
}

function drawCharts() {
  Object.entries(chartConfigs).forEach(([key, config]) => {
    document.querySelectorAll(`[data-chart="${key}"]`).forEach((canvas) => {
      if (canvas.offsetParent !== null) drawChart(canvas, config);
    });
    document.querySelectorAll(`[data-legend="${key}"]`).forEach((legend) => {
      renderLegend(legend, config);
    });
  });
}

function drawChart(canvas, config) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(280, rect.width || canvas.parentElement.clientWidth);
  const height = 210;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.height = `${height}px`;

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const padding = { top: 12, right: 12, bottom: 24, left: 44 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const allPoints = config.keys.flatMap((item) => state.series.get(item.key) || []);

  ctx.strokeStyle = "#e2e8f0";
  ctx.lineWidth = 1;
  for (let index = 0; index <= 4; index += 1) {
    const y = padding.top + (plotHeight / 4) * index;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }

  if (!allPoints.length) {
    ctx.fillStyle = "#64748b";
    ctx.font = "13px system-ui, sans-serif";
    ctx.fillText("Sem amostras no intervalo", padding.left, height / 2);
    return;
  }

  const maxTime = Math.max(...allPoints.map((point) => point.time));
  const minTime = maxTime - state.rangeSeconds;
  const visible = allPoints.filter((point) => point.time >= minTime);
  let maxValue = Math.max(...visible.map((point) => point.value), config.unit === "percent" ? 100 : 1);
  if (!Number.isFinite(maxValue) || maxValue <= 0) maxValue = 1;

  ctx.fillStyle = "#64748b";
  ctx.font = "11px system-ui, sans-serif";
  for (let index = 0; index <= 4; index += 1) {
    const value = maxValue - (maxValue / 4) * index;
    ctx.fillText(shortMetric(value, config.unit), 4, padding.top + (plotHeight / 4) * index + 4);
  }

  config.keys.forEach((item) => {
    const points = (state.series.get(item.key) || []).filter((point) => point.time >= minTime);
    if (!points.length) return;
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, index) => {
      const x = padding.left + ((point.time - minTime) / state.rangeSeconds) * plotWidth;
      const y = padding.top + plotHeight - (point.value / maxValue) * plotHeight;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });
}

function renderLegend(container, config) {
  container.replaceChildren(...config.keys.map((item) => {
    const label = document.createElement("span");
    label.className = "legend-item";
    const dot = document.createElement("i");
    dot.style.backgroundColor = item.color;
    const text = document.createElement("span");
    text.textContent = `${item.label}: ${formatMetric(latestValue(item.key), config.unit)}`;
    label.append(dot, text);
    return label;
  }));
}

function latestValue(key) {
  const points = state.series.get(key) || [];
  return points.length ? points.at(-1).value : null;
}

function configureTimers() {
  state.timers.forEach((timer) => clearInterval(timer));
  state.timers = [];
  if (!state.autoRefresh) return;
  state.timers = [
    setInterval(loadSnapshot, SNAPSHOT_INTERVAL_MS),
    setInterval(loadTimeseries, TIMESERIES_INTERVAL_MS),
    setInterval(loadRealtime, REALTIME_INTERVAL_MS),
  ];
}

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawCharts, 120);
});

const initialTab = window.location.hash.slice(1);
if (initialTab) activateTab(initialTab);
configureTimers();
refreshAll();
