import { fetchJson } from "./shared.js";

export const agnoApi = {
  entities() {
    return fetchJson("/api/agno/entities");
  },

  sessions(entityType, entityId) {
    const params = new URLSearchParams({ entity_type: entityType, entity_id: entityId });
    return fetchJson(`/api/agno/sessions?${params}`);
  },

  session(sessionId) {
    return fetchJson(`/api/agno/sessions/${encodeURIComponent(sessionId)}`);
  },

  deleteSession(sessionId) {
    return fetchJson(`/api/agno/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
  },

  metrics(entityType, entityId, days) {
    const params = new URLSearchParams({
      entity_type: entityType,
      entity_id: entityId,
      days: String(days),
    });
    return fetchJson(`/api/agno/metrics/summary?${params}`);
  },

  comparison(groupBy) {
    const params = new URLSearchParams({ group_by: groupBy, days: "30" });
    return fetchJson(`/api/agno/metrics/compare?${params}`);
  },

  report() {
    return fetchJson("/api/agno/metrics/report?days=30");
  },

  async run(payload) {
    const response = await fetch("/api/agno/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok || !response.body) {
      let detail = "";
      try {
        const error = await response.json();
        detail = error.detail || "";
      } catch {
        detail = await response.text();
      }
      throw new Error(detail || `HTTP ${response.status}`);
    }
    return response.body;
  },
};
