import { createAnalyticsController } from "./agno-analytics.js";
import { agnoApi } from "./agno-api.js";
import { readEventStream } from "./agno-stream.js";
import { escapeHtml, formatCurrency, formatDate, shortId } from "./shared.js";

const runEvents = new Set([
  "RunStarted", "RunCompleted", "RunError", "RunCancelled",
  "TeamRunStarted", "TeamRunCompleted", "TeamRunError", "TeamRunCancelled",
]);
const contentEvents = new Set(["RunContent", "TeamRunContent"]);

const params = new URLSearchParams(window.location.search);
const state = {
  entities: { agents: [], teams: [] },
  selected: null,
  sessions: [],
  sessionId: "",
  streaming: false,
  lastContent: "",
  requestedEntityId: params.get("entity_id") || "",
  requestedSessionId: params.get("session_id") || "",
};

const dom = {
  notice: document.getElementById("agno-notice"),
  overallStatus: document.getElementById("agno-overall-status"),
  statusCard: document.getElementById("agno-status-card"),
  updatedAt: document.getElementById("agno-updated-at"),
  agentCount: document.getElementById("agno-agent-count"),
  sourceState: document.getElementById("entity-source-state"),
  agentList: document.getElementById("agno-agent-list"),
  teamList: document.getElementById("agno-team-list"),
  sessionsList: document.getElementById("agno-sessions-list"),
  refresh: document.getElementById("agno-refresh"),
  newSession: document.getElementById("agno-new-session"),
  selectedTitle: document.getElementById("agno-selected-title"),
  selectedDetails: document.getElementById("agno-selected-details"),
  sessionPill: document.getElementById("agno-session-pill"),
  clearChat: document.getElementById("agno-clear-chat-btn"),
  chat: document.getElementById("agno-chat-log"),
  form: document.getElementById("agno-chat-form"),
  message: document.getElementById("agno-message"),
  submit: document.querySelector("#agno-chat-form button[type='submit']"),
  runFacts: document.getElementById("agno-run-facts"),
  events: document.getElementById("agno-event-list"),
  tabs: document.querySelectorAll(".agno-tab-btn"),
  views: document.querySelectorAll(".agno-console-view"),
};

const analytics = createAnalyticsController(() => state.selected);

dom.refresh.addEventListener("click", loadEntities);
dom.newSession.addEventListener("click", startNewSession);
dom.clearChat.addEventListener("click", () => {
  dom.chat.innerHTML = '<div class="empty-state">A tela foi limpa.</div>';
});
dom.tabs.forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.target)));
dom.form.addEventListener("submit", handleSubmit);
dom.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    dom.form.requestSubmit();
  }
});

loadEntities();

function switchTab(viewId) {
  dom.tabs.forEach((button) => {
    const active = button.dataset.target === viewId;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  dom.views.forEach((view) => view.classList.toggle("active", view.id === viewId));
  analytics.activate(viewId);
}

async function loadEntities() {
  setRefreshState(true);
  try {
    const payload = await agnoApi.entities();
    state.entities = payload.entities || { agents: [], teams: [] };
    renderStatus(payload.status || {});
    const selection = findInitialSelection();
    renderEntityLists();
    if (selection && (!state.selected || state.selected.id !== selection.entity.id || state.selected.type !== selection.type)) {
      await selectEntity(selection.entity, selection.type);
    } else if (!selection) {
      resetSelection();
    }
  } catch (error) {
    state.entities = { agents: [], teams: [] };
    renderStatus({ available: false, error: error.message });
    renderEntityLists();
  } finally {
    setRefreshState(false);
    dom.updatedAt.textContent = `Atualizado ${new Date().toLocaleTimeString("pt-BR")}`;
  }
}

function resetSelection() {
  state.selected = null;
  state.sessionId = "";
  state.sessions = [];
  dom.selectedTitle.textContent = "Selecione uma entidade";
  dom.selectedDetails.textContent = "";
  dom.sessionPill.textContent = "Sem sessão";
  dom.message.disabled = true;
  dom.submit.disabled = true;
  dom.chat.innerHTML = '<div class="empty-state">Nenhuma entidade disponível.</div>';
  dom.sessionsList.innerHTML = '<div class="empty-state">Nenhuma sessão.</div>';
  updateRunFacts({ Status: "indisponível" });
}

function findInitialSelection() {
  const agents = state.entities.agents || [];
  const teams = state.entities.teams || [];
  if (state.selected) {
    const current = (state.selected.type === "agent" ? agents : teams).find((item) => item.id === state.selected.id);
    if (current) return { entity: current, type: state.selected.type };
  }
  const requestedAgent = agents.find((item) => item.id === state.requestedEntityId);
  if (requestedAgent) return { entity: requestedAgent, type: "agent" };
  const requestedTeam = teams.find((item) => item.id === state.requestedEntityId);
  if (requestedTeam) return { entity: requestedTeam, type: "team" };
  if (agents[0]) return { entity: agents[0], type: "agent" };
  if (teams[0]) return { entity: teams[0], type: "team" };
  return null;
}

function renderStatus(status) {
  const available = Boolean(status.available);
  const detail = available ? "online" : status.error || "offline";
  dom.statusCard.classList.toggle("online", available);
  dom.statusCard.classList.toggle("offline", !available);
  dom.statusCard.querySelector(".status-state").textContent = detail;
  dom.overallStatus.className = `overall-status ${available ? "online" : "offline"}`;
  dom.overallStatus.textContent = available ? "Runtime conectado" : "Runtime indisponível";
  dom.sourceState.className = `source-state ${available ? "online" : "degraded"}`;
  dom.sourceState.textContent = available ? "Conectado" : "Indisponível";
  dom.notice.hidden = available;
  dom.notice.textContent = available ? "" : `Não foi possível consultar o runtime Agno: ${detail}`;
}

function renderEntityLists() {
  const agents = state.entities.agents || [];
  const teams = state.entities.teams || [];
  dom.agentCount.textContent = `${agents.length} agente(s), ${teams.length} time(s)`;
  renderEntityList(dom.agentList, agents, "agent", "Nenhum agente detectado.");
  renderEntityList(dom.teamList, teams, "team", "Nenhum time detectado.");
}

function renderEntityList(container, items, type, emptyText) {
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
    return;
  }
  container.innerHTML = "";
  for (const item of items) {
    const model = item.model || {};
    const button = document.createElement("button");
    button.type = "button";
    button.className = "entity-button";
    button.classList.toggle("active", state.selected?.id === item.id && state.selected?.type === type);
    button.innerHTML = `<strong>${escapeHtml(item.name || item.id)}</strong><small>${escapeHtml(model.model || model.name || "modelo padrão")}</small>`;
    button.addEventListener("click", () => selectEntity(item, type));
    container.appendChild(button);
  }
}

async function selectEntity(entity, type) {
  state.selected = { ...entity, type };
  state.sessionId = "";
  state.lastContent = "";
  dom.selectedTitle.textContent = entity.name || entity.id;
  const model = entity.model || {};
  dom.selectedDetails.innerHTML = `<code>${escapeHtml(type)}</code><span>${escapeHtml(entity.id)}</span><span>${escapeHtml(model.provider || "provedor padrão")}</span><span>${escapeHtml(model.model || model.name || "modelo padrão")}</span>`;
  dom.message.disabled = false;
  dom.submit.disabled = false;
  dom.sessionPill.textContent = "Nova sessão";
  dom.chat.innerHTML = '<div class="empty-state">Nova conversa.</div>';
  dom.events.innerHTML = '<div class="empty-state">Nenhum evento.</div>';
  updateRunFacts({ Entidade: `${type}/${entity.id}`, Sessão: "nova", Status: "pronto" });
  renderEntityLists();
  updateUrl();
  await loadSessions();
  dom.message.focus();
}

function startNewSession() {
  if (!state.selected) return;
  state.sessionId = "";
  state.lastContent = "";
  state.requestedSessionId = "";
  dom.sessionPill.textContent = "Nova sessão";
  dom.chat.innerHTML = '<div class="empty-state">Nova conversa.</div>';
  dom.events.innerHTML = '<div class="empty-state">Nenhum evento.</div>';
  updateRunFacts({ Entidade: `${state.selected.type}/${state.selected.id}`, Sessão: "nova", Status: "pronto" });
  renderSessions();
  updateUrl();
  dom.message.focus();
}

async function loadSessions() {
  if (!state.selected) return;
  try {
    const data = await agnoApi.sessions(state.selected.type, state.selected.id);
    state.sessions = data.sessions || [];
    renderSessions();
    if (state.requestedSessionId && state.sessions.some((item) => item.session_id === state.requestedSessionId)) {
      const requested = state.requestedSessionId;
      state.requestedSessionId = "";
      await openSession(requested);
    }
  } catch (error) {
    dom.sessionsList.innerHTML = `<div class="empty-state error-text">${escapeHtml(error.message)}</div>`;
  }
}

function renderSessions() {
  if (!state.sessions.length) {
    dom.sessionsList.innerHTML = '<div class="empty-state">Nenhuma sessão salva.</div>';
    return;
  }
  dom.sessionsList.innerHTML = "";
  for (const session of state.sessions) {
    const row = document.createElement("div");
    row.className = "session-item";
    row.classList.toggle("active", session.session_id === state.sessionId);
    row.innerHTML = `<button class="session-info" type="button"><strong>${escapeHtml(session.name || shortId(session.session_id))}</strong><small>${escapeHtml(formatDate(session.updated_at, { dateStyle: "short", timeStyle: "short" }))} · ${session.message_count || 0} msg</small></button><button class="session-delete" type="button" title="Excluir sessão" aria-label="Excluir sessão">×</button>`;
    row.querySelector(".session-info").addEventListener("click", () => openSession(session.session_id));
    row.querySelector(".session-delete").addEventListener("click", () => deleteSession(session.session_id));
    dom.sessionsList.appendChild(row);
  }
}

async function openSession(sessionId) {
  state.sessionId = sessionId;
  dom.sessionPill.textContent = `Sessão ${shortId(sessionId, 8)}`;
  dom.chat.innerHTML = '<div class="empty-state">Carregando sessão...</div>';
  renderSessions();
  updateUrl();
  try {
    renderSessionHistory(await agnoApi.session(sessionId));
  } catch (error) {
    dom.chat.innerHTML = `<div class="empty-state error-text">${escapeHtml(error.message)}</div>`;
  }
}

async function deleteSession(sessionId) {
  if (!window.confirm("Excluir esta sessão e as métricas associadas?")) return;
  try {
    await agnoApi.deleteSession(sessionId);
    state.sessions = state.sessions.filter((item) => item.session_id !== sessionId);
    if (state.sessionId === sessionId) startNewSession();
    else renderSessions();
  } catch (error) {
    dom.notice.hidden = false;
    dom.notice.textContent = `Falha ao excluir a sessão: ${error.message}`;
  }
}

function renderSessionHistory(data) {
  const messages = data.messages || [];
  const runs = data.runs_by_id || {};
  const tools = data.tools_by_run || {};
  const events = data.events_by_run || {};
  dom.chat.innerHTML = "";
  if (!messages.length) {
    dom.chat.innerHTML = '<div class="empty-state">Sessão vazia.</div>';
    return;
  }
  for (const message of messages) {
    appendMessage(message.role === "user" ? "user" : "agent", message.content, {
      createdAt: message.created_at,
      run: message.run_id ? runs[message.run_id] : null,
      tools: message.run_id ? tools[message.run_id] || [] : [],
      events: message.run_id ? events[message.run_id] || [] : [],
    });
  }
  const latestRun = (data.runs || []).at(-1);
  if (latestRun) {
    updateRunFacts({
      Entidade: `${latestRun.entity_type}/${latestRun.entity_id}`,
      Sessão: state.sessionId,
      Status: latestRun.status || "-",
      Duração: Number.isFinite(latestRun.duration_seconds)
        ? `${latestRun.duration_seconds.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}s`
        : "sem dado",
      TTFT: Number.isFinite(latestRun.ttft_seconds)
        ? `${(latestRun.ttft_seconds * 1000).toFixed(0)}ms`
        : "sem dado",
      Tokens: `${latestRun.input_tokens || 0} entrada · ${latestRun.output_tokens || 0} saída`,
      Custo: formatCurrency(latestRun.cost),
      Trace: shortId(latestRun.trace_id),
    });
    dom.events.innerHTML = "";
    for (const event of events[latestRun.run_id] || []) {
      const payload = parseStoredValue(event.event_data_json);
      addEvent(event.event_name || "RunEvent", summarizeEvent(payload || event));
    }
    if (!dom.events.children.length) {
      dom.events.innerHTML = '<div class="empty-state">Nenhum evento.</div>';
    }
  }
}

async function handleSubmit(event) {
  event.preventDefault();
  const message = dom.message.value.trim();
  if (!message || !state.selected || state.streaming) return;
  dom.message.value = "";
  await sendMessage(message);
}

async function sendMessage(message) {
  state.streaming = true;
  state.lastContent = "";
  dom.submit.disabled = true;
  dom.message.disabled = true;
  appendMessage("user", message, { createdAt: new Date().toISOString() });
  const assistant = appendMessage("agent", "", { createdAt: new Date().toISOString() });
  dom.events.innerHTML = "";
  addEvent("RunQueued", "Mensagem enviada");
  updateRunFacts({ Entidade: `${state.selected.type}/${state.selected.id}`, Sessão: state.sessionId || "nova", Status: "executando" });
  const startedAt = performance.now();
  const model = state.selected.model || {};
  let finalMeta = null;

  try {
    const body = await agnoApi.run({
      entity_type: state.selected.type,
      entity_id: state.selected.id,
      message,
      session_id: state.sessionId,
      model: model.model || model.name || "",
      model_provider: model.provider || "",
    });
    await readEventStream(body, (chunk) => {
      if (chunk.event === "RunFinished") finalMeta = chunk;
      else handleRunEvent(chunk, assistant);
    });
  } catch (error) {
    assistant.classList.add("error");
    assistant.querySelector(".message-content").textContent = `Erro na execução: ${error.message}`;
    addEvent("RunError", error.message);
  } finally {
    state.streaming = false;
    dom.submit.disabled = !state.selected;
    dom.message.disabled = !state.selected;
    const elapsed = (performance.now() - startedAt) / 1000;
    finalizeMessage(assistant, finalMeta, elapsed);
    updateRunFacts({
      Entidade: `${state.selected.type}/${state.selected.id}`,
      Sessão: state.sessionId || "salva",
      Status: finalMeta?.status || (assistant.classList.contains("error") ? "error" : "finalizado"),
      Duração: `${elapsed.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}s`,
      TTFT: Number.isFinite(finalMeta?.ttft_seconds) ? `${(finalMeta.ttft_seconds * 1000).toFixed(0)}ms` : "sem dado",
      Tokens: finalMeta?.tokens ? `${finalMeta.tokens.input} entrada · ${finalMeta.tokens.output} saída` : "sem dado",
      Custo: formatCurrency(finalMeta?.cost),
      Trace: shortId(finalMeta?.trace_id),
    });
    if (state.selected) await loadSessions();
    analytics.refreshMetrics();
    dom.message.focus();
  }
}

function handleRunEvent(chunk, assistant) {
  const event = chunk.event || "RunEvent";
  if (chunk.session_id) {
    state.sessionId = chunk.session_id;
    dom.sessionPill.textContent = `Sessão ${shortId(chunk.session_id, 8)}`;
    updateUrl();
  }
  if (runEvents.has(event) || event.includes("ToolCall") || event.includes("Reasoning")) {
    addEvent(event, summarizeEvent(chunk));
  }
  if (event.includes("ToolCall") && (event.endsWith("Completed") || event.endsWith("Error"))) {
    appendDrawerItem(assistant, "Ferramentas", chunk.tool_name || chunk.name || "ferramenta", chunk.tool_args || chunk.args);
  }
  if (event.includes("Reasoning")) {
    appendDrawerItem(assistant, "Raciocínio", "Passo", chunk.content || chunk.reasoning_content || "Registrado");
  }
  if (contentEvents.has(event)) appendAssistantContent(assistant, chunk.content);
  else if (event.endsWith("Completed") && chunk.content) setAssistantContent(assistant, chunk.content);
  else if (event.endsWith("Error") || event.endsWith("Cancelled")) {
    assistant.classList.add("error");
    appendAssistantContent(assistant, chunk.content || "Erro durante a execução.");
  }
}

function appendAssistantContent(assistant, content) {
  if (content == null) return;
  const value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  const unique = value.startsWith(state.lastContent) ? value.slice(state.lastContent.length) : value;
  assistant.querySelector(".message-content").textContent += unique;
  state.lastContent = value;
  dom.chat.scrollTop = dom.chat.scrollHeight;
}

function setAssistantContent(assistant, content) {
  const value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  assistant.querySelector(".message-content").textContent = value;
  state.lastContent = value;
}

function appendMessage(role, content, options = {}) {
  const row = document.createElement("article");
  row.className = `chat-message ${role}`;
  const author = role === "user" ? "Você" : state.selected?.name || "Agente";
  const time = options.createdAt ? formatDate(options.createdAt, { hour: "2-digit", minute: "2-digit" }) : "";
  row.innerHTML = `<div class="message-header"><span class="message-author">${escapeHtml(author)}</span><time class="message-time">${escapeHtml(time)}</time></div><div class="message-content"></div><div class="message-metrics"></div>`;
  row.querySelector(".message-content").textContent = content || "";
  if (role === "agent" && options.run) {
    renderStoredMetrics(row, options.run);
    if (options.tools?.length) {
      for (const tool of options.tools) appendDrawerItem(row, "Ferramentas", tool.tool_name, parseStoredValue(tool.tool_args_json));
    }
    const reasoning = (options.events || []).filter((item) => String(item.event_name || "").includes("Reasoning"));
    for (const item of reasoning) appendDrawerItem(row, "Raciocínio", "Passo", reasoningText(item));
  }
  dom.chat.appendChild(row);
  dom.chat.scrollTop = dom.chat.scrollHeight;
  return row;
}

function appendDrawerItem(message, title, name, value) {
  const className = `drawer-${title.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "")}`;
  let drawer = message.querySelector(`.${className}`);
  if (!drawer) {
    drawer = document.createElement("details");
    drawer.className = `message-drawer ${className}`;
    drawer.innerHTML = `<summary>${escapeHtml(title)}</summary><div class="drawer-body"></div>`;
    message.appendChild(drawer);
  }
  const item = document.createElement("div");
  item.className = "drawer-item";
  item.innerHTML = `<strong>${escapeHtml(name || "item")}</strong><br><code>${escapeHtml(displayValue(value))}</code>`;
  drawer.querySelector(".drawer-body").appendChild(item);
}

function finalizeMessage(message, meta, elapsed) {
  if (!message.querySelector(".message-content").textContent.trim()) {
    message.querySelector(".message-content").textContent = "Execução concluída sem conteúdo.";
  }
  const duration = Number.isFinite(meta?.duration_seconds) ? meta.duration_seconds : elapsed;
  const badges = [`${duration.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}s`];
  if (Number.isFinite(meta?.ttft_seconds)) badges.push(`TTFT ${(meta.ttft_seconds * 1000).toFixed(0)}ms`);
  if (meta?.tokens) badges.push(`${meta.tokens.input} in · ${meta.tokens.output} out · ${meta.tokens.total} total`);
  badges.push(formatCurrency(meta?.cost));
  if (meta?.trace_id) badges.push(`trace ${shortId(meta.trace_id)}`);
  message.querySelector(".message-metrics").innerHTML = badges.map((badge) => `<span class="metric-badge">${escapeHtml(badge)}</span>`).join("");
}

function renderStoredMetrics(message, run) {
  const badges = [];
  if (Number.isFinite(run.duration_seconds)) badges.push(`${run.duration_seconds.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}s`);
  if (Number.isFinite(run.ttft_seconds)) badges.push(`TTFT ${(run.ttft_seconds * 1000).toFixed(0)}ms`);
  if (run.total_tokens) badges.push(`${run.input_tokens || 0} in · ${run.output_tokens || 0} out · ${run.total_tokens} total`);
  badges.push(formatCurrency(run.cost));
  if (run.trace_id) badges.push(`trace ${shortId(run.trace_id)}`);
  message.querySelector(".message-metrics").innerHTML = badges.map((badge) => `<span class="metric-badge">${escapeHtml(badge)}</span>`).join("");
}

function addEvent(event, details) {
  const row = document.createElement("div");
  row.className = "event-row";
  row.innerHTML = `<strong>${escapeHtml(event)}</strong><small>${escapeHtml(details || "evento recebido")}</small>`;
  dom.events.prepend(row);
}

function updateRunFacts(facts) {
  dom.runFacts.innerHTML = Object.entries(facts).map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd title="${escapeHtml(value)}">${escapeHtml(value)}</dd></div>`).join("");
}

function summarizeEvent(chunk) {
  if (chunk.run_id) return `run ${shortId(chunk.run_id, 8)}`;
  if (chunk.tool_name) return `tool ${chunk.tool_name}`;
  if (typeof chunk.content === "string") return chunk.content.slice(0, 100);
  return "evento recebido";
}

function reasoningText(event) {
  const payload = parseStoredValue(event.event_data_json) || event.event_data || event;
  const data = payload?.data && typeof payload.data === "object" ? payload.data : payload;
  return data?.content || data?.reasoning_content || "Passo registrado";
}

function parseStoredValue(value) {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch { return value; }
}

function displayValue(value) {
  if (value == null || value === "") return "sem detalhes";
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function updateUrl() {
  if (!state.selected) return;
  const next = new URL(window.location.href);
  next.searchParams.set("entity_id", state.selected.id);
  if (state.sessionId) next.searchParams.set("session_id", state.sessionId);
  else next.searchParams.delete("session_id");
  window.history.replaceState({}, "", next);
}

function setRefreshState(loading) {
  dom.refresh.disabled = loading;
  dom.refresh.textContent = loading ? "Atualizando..." : "Atualizar";
}
