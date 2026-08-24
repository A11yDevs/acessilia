const agnoState = {
  entities: { agents: [], teams: [] },
  selected: null,
  sessionId: "",
  streaming: false,
  lastContent: "",
  startedAt: null,
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
  refresh: document.getElementById("agno-refresh"),
  selectedTitle: document.getElementById("agno-selected-title"),
  selectedDetails: document.getElementById("agno-selected-details"),
  chat: document.getElementById("agno-chat-log"),
  form: document.getElementById("agno-chat-form"),
  message: document.getElementById("agno-message"),
  submit: document.querySelector("#agno-chat-form button"),
  sessionPill: document.getElementById("agno-session-pill"),
  runFacts: document.getElementById("agno-run-facts"),
  eventList: document.getElementById("agno-event-list"),
};

dom.refresh.addEventListener("click", loadEntities);
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

loadEntities();

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
    dom.updatedAt.textContent = `Atualizado em ${new Date().toLocaleString("pt-BR")}`;
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
      <small>${escapeHtml(model.model || model.name || "modelo não informado")}</small>
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
    <span>${escapeHtml(model.provider || "provedor não informado")}</span>
    <span>${escapeHtml(model.model || model.name || "modelo não informado")}</span>
  `;
  dom.sessionPill.textContent = "Nova sessão";
  dom.message.disabled = false;
  dom.submit.disabled = false;
  dom.chat.innerHTML = "";
  dom.eventList.innerHTML = "";
  updateRunFacts({
    "Entidade": `${type}/${entity.id}`,
    "Sessão Agno": "nova",
    "Status": "pronto",
  });
  renderEntities();
  dom.message.focus();
}

async function sendMessage(message) {
  agnoState.streaming = true;
  agnoState.lastContent = "";
  agnoState.startedAt = performance.now();
  dom.submit.disabled = true;
  dom.message.disabled = true;
  appendMessage("user", message);
  const assistant = appendMessage("agent", "");
  addEvent("RunQueued", "Mensagem enviada ao proxy local.");
  updateRunFacts({
    "Entidade": `${agnoState.selected.type}/${agnoState.selected.id}`,
    "Sessão Agno": agnoState.sessionId || "nova",
    "Status": "executando",
  });

  try {
    const response = await fetch("/api/agno/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entity_type: agnoState.selected.type,
        entity_id: agnoState.selected.id,
        message,
        session_id: agnoState.sessionId,
      }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`Falha ao executar: HTTP ${response.status}`);
    }
    await readStream(response.body, (chunk) => handleChunk(chunk, assistant));
  } catch (error) {
    assistant.classList.add("error");
    assistant.querySelector(".message-content").textContent = String(error);
    addEvent("RunError", String(error));
  } finally {
    agnoState.streaming = false;
    dom.submit.disabled = !agnoState.selected;
    dom.message.disabled = !agnoState.selected;
    const elapsed = (performance.now() - agnoState.startedAt) / 1000;
    updateRunFacts({
      "Entidade": `${agnoState.selected.type}/${agnoState.selected.id}`,
      "Sessão Agno": agnoState.sessionId || "sem sessão",
      "Status": "finalizado",
      "Duração local": `${elapsed.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}s`,
    });
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
    dom.sessionPill.textContent = `Sessão ${chunk.session_id}`;
  }
  if (runEvents.has(event) || toolEvents.has(event) || event.includes("Reasoning")) {
    addEvent(event, summarizeChunk(chunk));
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
  assistant.querySelector(".message-content").textContent += unique;
  agnoState.lastContent = value;
  dom.chat.scrollTop = dom.chat.scrollHeight;
}

function setAssistantContent(assistant, content) {
  const value = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  assistant.querySelector(".message-content").textContent = value;
  agnoState.lastContent = value;
  dom.chat.scrollTop = dom.chat.scrollHeight;
}

function appendMessage(role, content) {
  const row = document.createElement("article");
  row.className = `chat-message ${role}`;
  row.innerHTML = `
    <span>${role === "user" ? "Você" : "Agno"}</span>
    <div class="message-content"></div>
  `;
  row.querySelector(".message-content").textContent = content;
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
  if (chunk.run_id) return `run ${chunk.run_id}`;
  if (chunk.tool?.tool_name) return `tool ${chunk.tool.tool_name}`;
  if (chunk.content && typeof chunk.content === "string") return chunk.content.slice(0, 120);
  return "evento recebido";
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
