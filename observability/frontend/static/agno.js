const agnoState = {
  entities: { agents: [], teams: [] },
  selected: null,
  sessionId: "",
  sessions: [],
  streaming: false,
  lastContent: "",
  startedAt: null,
  activeTab: "view-chat",
};

const runEvents = new Set([
  "RunStarted",
  "RunCompleted",
  "RunError",
  "RunCancelled",
  "TeamRunStarted",
  "TeamRunCompleted",
  "TeamRunError",
  "TeamRunCancelled",
]);

const contentEvents = new Set(["RunContent", "TeamRunContent"]);
const toolEvents = new Set(["ToolCallStarted", "ToolCallCompleted", "TeamToolCallStarted", "TeamToolCallCompleted"]);

const dom = {
  statusCard: document.getElementById("agno-status-card"),
  updatedAt: document.getElementById("agno-updated-at"),
  agentCount: document.getElementById("agno-agent-count"),
  agentList: document.getElementById("agno-agent-list"),
  teamList: document.getElementById("agno-team-list"),
  sessionsList: document.getElementById("agno-sessions-list"),
  newSessionBtn: document.getElementById("agno-new-session"),
  refresh: document.getElementById("agno-refresh"),
  selectedTitle: document.getElementById("agno-selected-title"),
  selectedDetails: document.getElementById("agno-selected-details"),
  chat: document.getElementById("agno-chat-log"),
  form: document.getElementById("agno-chat-form"),
  message: document.getElementById("agno-message"),
  submit: document.querySelector("#agno-chat-form button"),
  sessionPill: document.getElementById("agno-session-pill"),
  clearChatBtn: document.getElementById("agno-clear-chat-btn"),
  runFacts: document.getElementById("agno-run-facts"),
  eventList: document.getElementById("agno-event-list"),

  // Tabs
  tabBtns: document.querySelectorAll(".agno-tab-btn"),
  views: document.querySelectorAll(".agno-console-view"),

  // Metrics Tab (2B)
  metricsAgentTitle: document.getElementById("metrics-agent-title"),
  metricsDaysSelect: document.getElementById("metrics-days-select"),
  metricsRefreshBtn: document.getElementById("metrics-refresh-btn"),
  kpiTotalRuns: document.getElementById("kpi-total-runs"),
  kpiSuccessRate: document.getElementById("kpi-success-rate"),
  kpiAvgDuration: document.getElementById("kpi-avg-duration"),
  kpiP95Duration: document.getElementById("kpi-p95-duration"),
  kpiAvgTtft: document.getElementById("kpi-avg-ttft"),
  kpiP95Ttft: document.getElementById("kpi-p95-ttft"),
  kpiAvgTokens: document.getElementById("kpi-avg-tokens"),
  kpiTotalTokens: document.getElementById("kpi-total-tokens"),
  kpiTotalCost: document.getElementById("kpi-total-cost"),
  agentRunsTbody: document.getElementById("agent-runs-tbody"),

  // Compare Tab (2B)
  compareGroupSelect: document.getElementById("compare-group-select"),
  compareRefreshBtn: document.getElementById("compare-refresh-btn"),
  compareColHeader: document.getElementById("compare-col-header"),
  compareTbody: document.getElementById("compare-tbody"),

  // Report Tab (2B)
  reportCopyBtn: document.getElementById("report-copy-btn"),
  reportRefreshBtn: document.getElementById("report-refresh-btn"),
  reportMarkdownPreview: document.getElementById("report-markdown-preview"),
};

// Event Listeners
dom.refresh.addEventListener("click", loadEntities);
dom.newSessionBtn?.addEventListener("click", startNewSession);
dom.clearChatBtn?.addEventListener("click", clearChatView);

dom.tabBtns.forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.target));
});

dom.metricsRefreshBtn?.addEventListener("click", loadMetricsView);
dom.metricsDaysSelect?.addEventListener("change", loadMetricsView);

dom.compareRefreshBtn?.addEventListener("click", loadCompareView);
dom.compareGroupSelect?.addEventListener("change", loadCompareView);

dom.reportRefreshBtn?.addEventListener("click", loadReportView);
dom.reportCopyBtn?.addEventListener("click", copyReportMarkdown);

dom.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = dom.message.value.trim();
  if (!message || !agnoState.selected || agnoState.streaming) return;
  dom.message.value = "";
  await sendMessage(message);
});

dom.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    dom.form.requestSubmit();
  }
});

// Inicialização
loadEntities();

function switchTab(targetId) {
  agnoState.activeTab = targetId;
  dom.tabBtns.forEach((b) => b.classList.toggle("active", b.dataset.target === targetId));
  dom.views.forEach((v) => v.classList.toggle("active", v.id === targetId));

  if (targetId === "view-metrics") loadMetricsView();
  if (targetId === "view-compare") loadCompareView();
  if (targetId === "view-report") loadReportView();
}

async function loadEntities() {
  setLoading(true);
  try {
    const response = await fetch("/api/agno/entities", { cache: "no-store" });
    const payload = await response.json();
    agnoState.entities = payload.entities || { agents: [], teams: [] };
    renderStatus(payload.status || {});
    renderEntities();
  } catch (error) {
    renderStatus({ available: false, error: String(error) });
    renderEmptyList(dom.agentList, "AgentOS indisponível.");
    renderEmptyList(dom.teamList, "Sem times detectados.");
  } finally {
    setLoading(false);
    dom.updatedAt.textContent = `Atualizado em ${new Date().toLocaleTimeString("pt-BR")}`;
  }
}

function renderStatus(status) {
  dom.statusCard.classList.toggle("online", Boolean(status.available));
  dom.statusCard.classList.toggle("offline", !status.available);
  dom.statusCard.querySelector(".status-state").textContent = status.available
    ? "online"
    : status.error || `offline${status.status_code ? ` (${status.status_code})` : ""}`;
}

function renderEntities() {
  const agents = agnoState.entities.agents || [];
  const teams = agnoState.entities.teams || [];
  dom.agentCount.textContent = `${agents.length} agente(s), ${teams.length} time(s)`;
  renderEntityList(dom.agentList, agents, "agent", "Nenhum agente detectado.");
  renderEntityList(dom.teamList, teams, "team", "Nenhum time detectado.");

  if (!agnoState.selected && agents.length > 0) {
    selectEntity(agents[0], "agent");
  }
}

function renderEntityList(container, items, type, emptyText) {
  container.innerHTML = "";
  if (!items.length) {
    renderEmptyList(container, emptyText);
    return;
  }

  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "entity-card";
    button.dataset.entityId = item.id;
    button.dataset.entityType = type;
    if (agnoState.selected?.id === item.id && agnoState.selected?.type === type) {
      button.classList.add("active");
    }

    const model = item.model || {};
    button.innerHTML = `
      <strong>${escapeHtml(item.name || item.id)}</strong>
      <small>${escapeHtml(model.model || model.name || "modelo padrão")}</small>
    `;
    button.addEventListener("click", () => selectEntity(item, type));
    container.appendChild(button);
  });
}

function renderEmptyList(container, text) {
  container.innerHTML = `<div class="entity-placeholder">${escapeHtml(text)}</div>`;
}

function selectEntity(entity, type) {
  agnoState.selected = { ...entity, type };
  agnoState.sessionId = "";
  agnoState.lastContent = "";
  dom.selectedTitle.textContent = entity.name || entity.id;
  const model = entity.model || {};
  dom.selectedDetails.innerHTML = `
    <code>${escapeHtml(type)}</code>
    <span>${escapeHtml(entity.id)}</span>
    <span>${escapeHtml(model.provider || "provedor padrão")}</span>
    <span>${escapeHtml(model.model || model.name || "modelo padrão")}</span>
  `;
  dom.sessionPill.textContent = "Nova sessão";
  dom.message.disabled = false;
  dom.submit.disabled = false;
  dom.chat.innerHTML = "";
  dom.eventList.innerHTML = "";
  updateRunFacts({
    "Entidade": `${type}/${entity.id}`,
    "Sessão": "nova",
    "Status": "pronto",
  });
  renderEntities();
  loadSessions(type, entity.id);
  dom.message.focus();
}

function startNewSession() {
  agnoState.sessionId = "";
  agnoState.lastContent = "";
  dom.sessionPill.textContent = "Nova sessão";
  dom.chat.innerHTML = `
    <div class="agno-empty">
      <h3>Nova conversa com ${escapeHtml(agnoState.selected?.name || agnoState.selected?.id || "o agente")}</h3>
      <p>Envie uma mensagem abaixo para iniciar uma nova sessão persistida no SQLite.</p>
    </div>
  `;
  dom.eventList.innerHTML = "";
  updateRunFacts({
    "Entidade": `${agnoState.selected?.type}/${agnoState.selected?.id}`,
    "Sessão": "nova",
    "Status": "pronto",
  });
  if (agnoState.selected) {
    loadSessions(agnoState.selected.type, agnoState.selected.id);
  }
}

function clearChatView() {
  dom.chat.innerHTML = `
    <div class="agno-empty">
      <h3>Tela limpa</h3>
      <p>Envie uma mensagem para continuar na sessão atual ou clique em "+ Nova" para trocar de sessão.</p>
    </div>
  `;
}

async function loadSessions(entityType, entityId) {
  if (!dom.sessionsList) return;
  try {
    const res = await fetch(`/api/agno/sessions?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}`);
    const data = await res.json();
    agnoState.sessions = data.sessions || [];
    renderSessionsList();
  } catch (err) {
    dom.sessionsList.innerHTML = `<div class="entity-placeholder">Erro ao carregar histórico: ${escapeHtml(err.message)}</div>`;
  }
}

function renderSessionsList() {
  if (!dom.sessionsList) return;
  dom.sessionsList.innerHTML = "";
  if (!agnoState.sessions.length) {
    dom.sessionsList.innerHTML = `<div class="entity-placeholder">Nenhuma sessão anterior salva.</div>`;
    return;
  }

  agnoState.sessions.forEach((s) => {
    const item = document.createElement("div");
    item.className = "session-item";
    if (agnoState.sessionId === s.session_id) item.classList.add("active");

    const dateStr = s.updated_at ? new Date(s.updated_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
    item.innerHTML = `
      <div class="session-info">
        <strong>${escapeHtml(s.name || s.session_id)}</strong>
        <small>${escapeHtml(dateStr)} • ${s.message_count || 0} msg(s)</small>
      </div>
      <button class="session-del-btn" type="button" title="Excluir sessão">×</button>
    `;

    item.querySelector(".session-info").addEventListener("click", () => openSession(s.session_id));
    item.querySelector(".session-del-btn").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteSession(s.session_id);
    });

    dom.sessionsList.appendChild(item);
  });
}

async function openSession(sessionId) {
  agnoState.sessionId = sessionId;
  dom.sessionPill.textContent = `Sessão ${sessionId.slice(-6)}`;
  dom.chat.innerHTML = `<div class="entity-placeholder">Carregando mensagens da sessão...</div>`;
  renderSessionsList();

  try {
    const res = await fetch(`/api/agno/sessions/${encodeURIComponent(sessionId)}`);
    if (!res.ok) throw new Error("Falha ao buscar sessão");
    const data = await res.json();
    renderSessionHistory(data);
  } catch (err) {
    dom.chat.innerHTML = `<div class="entity-placeholder error">Erro ao carregar histórico: ${escapeHtml(err.message)}</div>`;
  }
}

async function deleteSession(sessionId) {
  if (!confirm("Excluir esta sessão e todas as métricas associadas?")) return;
  try {
    await fetch(`/api/agno/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    if (agnoState.sessionId === sessionId) {
      startNewSession();
    } else if (agnoState.selected) {
      loadSessions(agnoState.selected.type, agnoState.selected.id);
    }
  } catch (err) {
    alert(`Erro ao excluir sessão: ${err.message}`);
  }
}

function renderSessionHistory(data) {
  dom.chat.innerHTML = "";
  const messages = data.messages || [];
  const runsById = data.runs_by_id || {};
  const toolsByRun = data.tools_by_run || {};
  const eventsByRun = data.events_by_run || {};

  if (!messages.length) {
    dom.chat.innerHTML = `<div class="agno-empty"><h3>Sessão vazia</h3><p>Envie uma mensagem para começar.</p></div>`;
    return;
  }

  messages.forEach((msg) => {
    const role = msg.role === "user" ? "user" : "agent";
    const run = msg.run_id ? runsById[msg.run_id] : null;
    const tools = msg.run_id ? (toolsByRun[msg.run_id] || []) : [];
    const events = msg.run_id ? (eventsByRun[msg.run_id] || []) : [];

    const row = appendMessage(role, msg.content, {
      createdAt: msg.created_at,
      run,
      tools,
      events,
    });
  });
}

// --- ENVIO DE MENSAGEM & STREAMING COM MÉTRICAS (2A) ---

async function sendMessage(message) {
  agnoState.streaming = true;
  agnoState.lastContent = "";
  agnoState.startedAt = performance.now();
  dom.submit.disabled = true;
  dom.message.disabled = true;

  // Renderiza bolha do usuário
  appendMessage("user", message, { createdAt: new Date().toISOString() });

  // Cria bolha do assistente em estado de carregamento
  const assistantBubble = appendMessage("agent", "", {
    createdAt: new Date().toISOString(),
    inProgress: true,
  });

  addEvent("RunQueued", "Mensagem enviada ao proxy local.");
  updateRunFacts({
    "Entidade": `${agnoState.selected.type}/${agnoState.selected.id}`,
    "Sessão": agnoState.sessionId || "nova",
    "Status": "executando",
  });

  const modelInfo = agnoState.selected.model || {};
  let currentRunMeta = null;

  try {
    const response = await fetch("/api/agno/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_type: agnoState.selected.type,
        entity_id: agnoState.selected.id,
        message,
        session_id: agnoState.sessionId,
        model: modelInfo.model || modelInfo.name || "",
        model_provider: modelInfo.provider || "",
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error(`Falha ao executar: HTTP ${response.status}`);
    }

    await readStream(response.body, (chunk) => {
      if (chunk.event === "RunFinished") {
        currentRunMeta = chunk;
      } else {
        handleChunk(chunk, assistantBubble);
      }
    });

  } catch (error) {
    assistantBubble.classList.add("error");
    const contentEl = assistantBubble.querySelector(".message-content");
    contentEl.textContent = `Erro na execução: ${error.message}`;
    addEvent("RunError", String(error));
  } finally {
    agnoState.streaming = false;
    dom.submit.disabled = !agnoState.selected;
    dom.message.disabled = !agnoState.selected;

    const elapsed = (performance.now() - agnoState.startedAt) / 1000;

    // Atualiza badges finais da mensagem com as métricas persistidas
    finalizeAssistantMessage(assistantBubble, currentRunMeta, elapsed);

    // Atualiza facts do painel lateral
    updateRunFacts({
      "Entidade": `${agnoState.selected.type}/${agnoState.selected.id}`,
      "Sessão": agnoState.sessionId || "salva",
      "Status": currentRunMeta?.status || "finalizado",
      "Duração local": `${elapsed.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}s`,
      "TTFT": currentRunMeta?.ttft_seconds ? `${(currentRunMeta.ttft_seconds * 1000).toFixed(0)}ms` : "N/A",
      "Tokens": currentRunMeta?.tokens ? `in:${currentRunMeta.tokens.input} out:${currentRunMeta.tokens.output}` : "N/A",
      "Custo": currentRunMeta?.cost != null ? `US$ ${currentRunMeta.cost.toFixed(6)}` : "Sem dado",
      "Trace": currentRunMeta?.trace_id ? currentRunMeta.trace_id.slice(0, 12) : "N/A",
    });

    // Recarrega sessões
    if (agnoState.selected) {
      loadSessions(agnoState.selected.type, agnoState.selected.id);
    }
    dom.message.focus();
  }
}

async function readStream(body, onChunk) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = parseBuffer(buffer, onChunk);
  }
  parseBuffer(buffer, onChunk);
}

function parseBuffer(buffer, onChunk) {
  let start = buffer.indexOf("{");
  while (start !== -1) {
    let depth = 0;
    let inString = false;
    let escaped = false;
    let end = -1;

    for (let index = start; index < buffer.length; index += 1) {
      const char = buffer[index];
      if (inString) {
        if (escaped) escaped = false;
        else if (char === "\\") escaped = true;
        else if (char === "\"") inString = false;
      } else if (char === "\"") {
        inString = true;
      } else if (char === "{") {
        depth += 1;
      } else if (char === "}") {
        depth -= 1;
        if (depth === 0) {
          end = index;
          break;
        }
      }
    }

    if (end === -1) return buffer.slice(start);

    const raw = buffer.slice(start, end + 1);
    try {
      onChunk(normalizeChunk(JSON.parse(raw)));
    } catch {
      return buffer.slice(start + 1);
    }
    buffer = buffer.slice(end + 1).trim();
    start = buffer.indexOf("{");
  }
  return buffer;
}

function normalizeChunk(chunk) {
  if (chunk && typeof chunk === "object" && "event" in chunk && !("data" in chunk)) {
    return chunk;
  }
  if (chunk && typeof chunk === "object" && "event" in chunk && "data" in chunk) {
    let data = chunk.data;
    if (typeof data === "string") {
      try {
        data = JSON.parse(data);
      } catch {
        data = {};
      }
    }
    return { event: chunk.event, ...(data || {}) };
  }
  return chunk;
}

function handleChunk(chunk, assistant) {
  const event = chunk.event || "RunEvent";
  if (chunk.session_id) {
    agnoState.sessionId = chunk.session_id;
    dom.sessionPill.textContent = `Sessão ${chunk.session_id.slice(-6)}`;
  }

  if (runEvents.has(event) || toolEvents.has(event) || event.includes("Reasoning")) {
    addEvent(event, summarizeChunk(chunk));
  }

  // Acumula tool calls live
  if (toolEvents.has(event)) {
    appendToolCall(assistant, chunk);
  }

  // Acumula reasoning live
  if (event.includes("Reasoning")) {
    appendReasoning(assistant, chunk);
  }

  if (contentEvents.has(event)) {
    appendAssistantContent(assistant, chunk.content);
  } else if (event.endsWith("Completed") && chunk.content) {
    setAssistantContent(assistant, chunk.content);
  } else if (event.endsWith("Error") || event.endsWith("Cancelled")) {
    assistant.classList.add("error");
    appendAssistantContent(assistant, chunk.content || "Erro durante a execução.");
  }
}

function appendAssistantContent(assistant, content) {
  if (content == null) return;
  const value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  const unique = value.startsWith(agnoState.lastContent)
    ? value.slice(agnoState.lastContent.length)
    : value;
  const contentEl = assistant.querySelector(".message-content");
  contentEl.textContent += unique;
  agnoState.lastContent = value;
  dom.chat.scrollTop = dom.chat.scrollHeight;
}

function setAssistantContent(assistant, content) {
  const value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  const contentEl = assistant.querySelector(".message-content");
  contentEl.textContent = value;
  agnoState.lastContent = value;
  dom.chat.scrollTop = dom.chat.scrollHeight;
}

function appendToolCall(assistant, chunk) {
  let toolsDrawer = assistant.querySelector(".tools-drawer");
  if (!toolsDrawer) {
    toolsDrawer = document.createElement("details");
    toolsDrawer.className = "tools-drawer";
    toolsDrawer.innerHTML = `<summary>🛠️ Ferramentas acionadas</summary><div class="tools-body"></div>`;
    assistant.querySelector(".message-body").appendChild(toolsDrawer);
  }
  const body = toolsDrawer.querySelector(".tools-body");
  const toolDiv = document.createElement("div");
  toolDiv.className = "tool-item";
  const name = chunk.tool_name || chunk.name || "ferramenta";
  toolDiv.innerHTML = `<strong>${escapeHtml(name)}</strong>: <small>${escapeHtml(JSON.stringify(chunk.args || chunk.tool_args || ""))}</small>`;
  body.appendChild(toolDiv);
}

function appendReasoning(assistant, chunk) {
  let reasoningDrawer = assistant.querySelector(".reasoning-drawer");
  if (!reasoningDrawer) {
    reasoningDrawer = document.createElement("details");
    reasoningDrawer.className = "reasoning-drawer";
    reasoningDrawer.innerHTML = `<summary>🧠 Passos de Raciocínio</summary><div class="reasoning-body"></div>`;
    assistant.querySelector(".message-body").appendChild(reasoningDrawer);
  }
  const body = reasoningDrawer.querySelector(".reasoning-body");
  const stepDiv = document.createElement("div");
  stepDiv.className = "reasoning-step";
  stepDiv.textContent = chunk.content || chunk.reasoning_content || "Passo de raciocínio executado.";
  body.appendChild(stepDiv);
}

function finalizeAssistantMessage(assistant, runMeta, elapsed) {
  const metricsBar = assistant.querySelector(".message-metrics");
  if (!metricsBar) return;

  const dur = runMeta?.duration_seconds ? `${runMeta.duration_seconds}s` : `${elapsed.toFixed(2)}s`;
  const ttft = runMeta?.ttft_seconds ? `${(runMeta.ttft_seconds * 1000).toFixed(0)}ms` : null;
  const tokens = runMeta?.tokens;
  const cost = runMeta?.cost;

  let badges = `
    <span class="metric-badge" title="Duração total">⏱️ ${dur}</span>
  `;
  if (ttft) {
    badges += `<span class="metric-badge" title="Time To First Token">⚡ TTFT ${ttft}</span>`;
  }
  if (tokens && tokens.total) {
    badges += `<span class="metric-badge" title="Tokens In / Out / Total">🔢 in:${tokens.input} out:${tokens.output} total:${tokens.total}</span>`;
    if (tokens.reasoning) {
      badges += `<span class="metric-badge" title="Reasoning Tokens">🧠 ${tokens.reasoning}</span>`;
    }
  }
  if (cost != null) {
    badges += `<span class="metric-badge highlight" title="Custo informado pelo provedor">💰 US$ ${cost.toFixed(6)}</span>`;
  } else {
    badges += `<span class="metric-badge muted-badge" title="Custo não reportado pelo provedor">💰 Custo: Sem dado</span>`;
  }
  if (runMeta?.trace_id) {
    badges += `<span class="metric-badge" title="Trace ID">trace ${escapeHtml(runMeta.trace_id.slice(0, 12))}</span>`;
  }

  metricsBar.innerHTML = badges;
}

// --- RENDERIZADOR DE BOLHA DE MENSAGEM COM BLOCOS ESTRUTURADOS ---

function appendMessage(role, content, options = {}) {
  const row = document.createElement("article");
  row.className = `chat-message ${role}`;

  const timeStr = options.createdAt ? new Date(options.createdAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "";
  const title = role === "user" ? "Você" : (agnoState.selected?.name || "Agente Agno");

  let html = `
    <div class="message-header">
      <span class="message-author">${escapeHtml(title)}</span>
      <span class="message-time">${escapeHtml(timeStr)}</span>
    </div>
    <div class="message-body">
      <div class="message-content"></div>
      <div class="message-metrics"></div>
    </div>
  `;

  row.innerHTML = html;
  row.querySelector(".message-content").textContent = content;

  // Se já temos dados do run (histórico)
  if (role === "agent" && options.run) {
    const run = options.run;
    const dur = run.duration_seconds ? `${run.duration_seconds.toFixed(2)}s` : "-";
    const ttft = run.ttft_seconds ? `${(run.ttft_seconds * 1000).toFixed(0)}ms` : null;
    let badges = `<span class="metric-badge">⏱️ ${dur}</span>`;
    if (ttft) badges += `<span class="metric-badge">⚡ TTFT ${ttft}</span>`;
    if (run.total_tokens) {
      badges += `<span class="metric-badge">🔢 in:${run.input_tokens} out:${run.output_tokens} total:${run.total_tokens}</span>`;
      if (run.reasoning_tokens) badges += `<span class="metric-badge">🧠 ${run.reasoning_tokens}</span>`;
    }
    if (run.cost != null) {
      badges += `<span class="metric-badge highlight">💰 US$ ${run.cost.toFixed(6)}</span>`;
    } else {
      badges += `<span class="metric-badge muted-badge">💰 Custo: Sem dado</span>`;
    }
    if (run.trace_id) {
      badges += `<span class="metric-badge" title="Trace ID">trace ${escapeHtml(run.trace_id.slice(0, 12))}</span>`;
    }
    row.querySelector(".message-metrics").innerHTML = badges;

    // Tool calls do histórico
    if (options.tools && options.tools.length) {
      const toolsDrawer = document.createElement("details");
      toolsDrawer.className = "tools-drawer";
      toolsDrawer.innerHTML = `<summary>🛠️ ${options.tools.length} ferramenta(s) acionada(s)</summary><div class="tools-body"></div>`;
      const body = toolsDrawer.querySelector(".tools-body");
      options.tools.forEach((t) => {
        const item = document.createElement("div");
        item.className = "tool-item";
        item.innerHTML = `<strong>${escapeHtml(t.tool_name)}</strong> <small>(${escapeHtml(t.status)})</small>: <code>${escapeHtml(t.tool_args_json || "")}</code>`;
        body.appendChild(item);
      });
      row.querySelector(".message-body").appendChild(toolsDrawer);
    }

    const reasoningEvents = (options.events || []).filter((event) => {
      const name = String(event.event_name || event.event || "");
      return name.includes("Reasoning");
    });
    if (reasoningEvents.length) {
      const reasoningDrawer = document.createElement("details");
      reasoningDrawer.className = "reasoning-drawer";
      reasoningDrawer.innerHTML = `<summary>🧠 ${reasoningEvents.length} passo(s) de raciocínio</summary><div class="reasoning-body"></div>`;
      const body = reasoningDrawer.querySelector(".reasoning-body");
      reasoningEvents.forEach((event) => {
        const item = document.createElement("div");
        item.className = "reasoning-step";
        item.textContent = reasoningTextFromEvent(event);
        body.appendChild(item);
      });
      row.querySelector(".message-body").appendChild(reasoningDrawer);
    }
  }

  dom.chat.appendChild(row);
  dom.chat.scrollTop = dom.chat.scrollHeight;
  return row;
}

function addEvent(event, details) {
  const row = document.createElement("div");
  row.className = "event-row";
  row.innerHTML = `
    <strong>${escapeHtml(event)}</strong>
    <small>${escapeHtml(details || "evento recebido")}</small>
  `;
  dom.eventList.prepend(row);
}

function updateRunFacts(facts) {
  dom.runFacts.innerHTML = Object.entries(facts)
    .map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`)
    .join("");
}

function summarizeChunk(chunk) {
  if (chunk.run_id) return `run ${chunk.run_id.slice(-6)}`;
  if (chunk.tool?.tool_name) return `tool ${chunk.tool.tool_name}`;
  if (chunk.content && typeof chunk.content === "string") return chunk.content.slice(0, 100);
  return "evento recebido";
}

function reasoningTextFromEvent(event) {
  let payload = event.event_data ?? event;
  if (event.event_data_json) {
    try {
      payload = JSON.parse(event.event_data_json);
    } catch {
      payload = event.event_data_json;
    }
  }

  if (payload && typeof payload === "object" && payload.data && typeof payload.data === "object") {
    payload = payload.data;
  }

  const value = payload?.content ?? payload?.reasoning_content ?? payload?.reasoning;
  if (value == null) return "Passo de raciocínio registrado.";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

// --- ETAPA 2B: MÉTRICAS DO AGENTE, COMPARATIVO E RELATÓRIO ---

async function loadMetricsView() {
  if (!agnoState.selected) {
    dom.metricsAgentTitle.textContent = "Selecione um agente na lateral";
    return;
  }

  dom.metricsAgentTitle.textContent = `Métricas de ${agnoState.selected.name || agnoState.selected.id}`;
  const days = dom.metricsDaysSelect?.value || 30;

  try {
    const res = await fetch(`/api/agno/metrics/summary?entity_id=${encodeURIComponent(agnoState.selected.id)}&entity_type=${encodeURIComponent(agnoState.selected.type)}&days=${days}`);
    const data = await res.json();
    renderAgentKpis(data);
  } catch (err) {
    alert(`Erro ao buscar métricas do agente: ${err.message}`);
  }
}

function renderAgentKpis(data) {
  dom.kpiTotalRuns.textContent = data.total_runs || 0;
  dom.kpiSuccessRate.textContent = `${(100 - (data.error_rate || 0)).toFixed(1)}% taxa de sucesso`;

  dom.kpiAvgDuration.textContent = data.avg_duration ? `${data.avg_duration}s` : "-";
  dom.kpiP95Duration.textContent = data.p95_duration ? `p95: ${data.p95_duration}s | p50: ${data.p50_duration}s` : "sem dados suficientes";

  dom.kpiAvgTtft.textContent = data.avg_ttft ? `${(data.avg_ttft * 1000).toFixed(0)}ms` : "-";
  dom.kpiP95Ttft.textContent = data.p95_ttft ? `p95: ${(data.p95_ttft * 1000).toFixed(0)}ms` : "sem dados suficientes";

  dom.kpiAvgTokens.textContent = data.avg_tokens ? `${data.avg_tokens}` : "-";
  dom.kpiTotalTokens.textContent = `in: ${data.input_tokens_total} | out: ${data.output_tokens_total}`;

  dom.kpiTotalCost.textContent = data.total_cost != null ? `US$ ${data.total_cost.toFixed(6)}` : "Sem dado";

  // Tabela de execuções
  dom.agentRunsTbody.innerHTML = "";
  const recent = data.recent_runs || [];
  if (!recent.length) {
    dom.agentRunsTbody.innerHTML = `<tr><td colspan="7" class="text-center muted">Nenhuma execução registrada no período.</td></tr>`;
    return;
  }

  recent.forEach((r) => {
    const dateStr = r.created_at ? new Date(r.created_at).toLocaleString("pt-BR") : "";
    const durStr = r.duration_seconds ? `${r.duration_seconds.toFixed(2)}s` : "-";
    const ttftStr = r.ttft_seconds ? `${(r.ttft_seconds * 1000).toFixed(0)}ms` : "-";
    const costStr = r.cost != null ? `US$ ${r.cost.toFixed(6)}` : "Sem dado";
    const statusClass = r.status === "error" ? "badge-error" : "badge-ok";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(dateStr)}</td>
      <td><span class="status-badge ${statusClass}">${escapeHtml(r.status)}</span></td>
      <td><code>${escapeHtml(r.model || "padrão")}</code></td>
      <td>${escapeHtml(durStr)}</td>
      <td>${escapeHtml(ttftStr)}</td>
      <td>${r.input_tokens || 0} / ${r.output_tokens || 0} / <strong>${r.total_tokens || 0}</strong></td>
      <td>${escapeHtml(costStr)}</td>
    `;
    dom.agentRunsTbody.appendChild(tr);
  });
}

async function loadCompareView() {
  const groupBy = dom.compareGroupSelect?.value || "agent";
  dom.compareColHeader.textContent = groupBy === "agent" ? "Agente" : "Modelo";
  dom.compareTbody.innerHTML = `<tr><td colspan="8" class="text-center muted">Atualizando dados comparativos...</td></tr>`;

  try {
    const res = await fetch(`/api/agno/metrics/compare?group_by=${groupBy}&days=30`);
    const data = await res.json();
    renderCompareTable(data.items || []);
  } catch (err) {
    dom.compareTbody.innerHTML = `<tr><td colspan="8" class="text-center error">Erro ao carregar comparativo: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function renderCompareTable(items) {
  dom.compareTbody.innerHTML = "";
  if (!items.length) {
    dom.compareTbody.innerHTML = `<tr><td colspan="8" class="text-center muted">Sem dados suficientes para comparação.</td></tr>`;
    return;
  }

  items.forEach((item) => {
    const durStr = item.avg_duration ? `${item.avg_duration}s` : "-";
    const ttftStr = item.avg_ttft ? `${(item.avg_ttft * 1000).toFixed(0)}ms` : "-";
    const costStr = item.total_cost != null ? `US$ ${item.total_cost.toFixed(6)}` : "Sem dado";

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(item.group_key)}</strong></td>
      <td>${escapeHtml(item.model_provider || "-")}</td>
      <td>${item.total_calls}</td>
      <td><strong>${item.success_rate}%</strong></td>
      <td>${durStr}</td>
      <td>${ttftStr}</td>
      <td>${item.avg_tokens}</td>
      <td>${costStr}</td>
    `;
    dom.compareTbody.appendChild(tr);
  });
}

async function loadReportView() {
  dom.reportMarkdownPreview.textContent = "Gerando relatório detalhado de observabilidade...";
  try {
    const res = await fetch("/api/agno/metrics/report?days=30");
    const data = await res.json();
    dom.reportMarkdownPreview.textContent = data.markdown || "Relatório vazio.";
  } catch (err) {
    dom.reportMarkdownPreview.textContent = `Erro ao gerar relatório: ${err.message}`;
  }
}

function copyReportMarkdown() {
  const text = dom.reportMarkdownPreview.textContent;
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const originalText = dom.reportCopyBtn.textContent;
    dom.reportCopyBtn.textContent = "✅ Copiado!";
    setTimeout(() => {
      dom.reportCopyBtn.textContent = originalText;
    }, 2000);
  }).catch((err) => {
    alert("Falha ao copiar para a área de transferência.");
  });
}

function setLoading(loading) {
  dom.refresh.disabled = loading;
  dom.refresh.textContent = loading ? "Atualizando..." : "Atualizar";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
