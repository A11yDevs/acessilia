import { agnoApi } from "./agno-api.js";
import { copyText, escapeHtml, formatCurrency, formatDate } from "./shared.js";

function seconds(value) {
  return Number.isFinite(value) ? `${value.toLocaleString("pt-BR", { maximumFractionDigits: 3 })}s` : "-";
}

function milliseconds(value) {
  return Number.isFinite(value) ? `${(value * 1000).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}ms` : "-";
}

function numberOrDash(value, maximumFractionDigits = 0) {
  return Number.isFinite(value)
    ? value.toLocaleString("pt-BR", { maximumFractionDigits })
    : "-";
}

export function createAnalyticsController(getSelected) {
  const dom = {
    title: document.getElementById("metrics-agent-title"),
    days: document.getElementById("metrics-days-select"),
    refresh: document.getElementById("metrics-refresh-btn"),
    totalRuns: document.getElementById("kpi-total-runs"),
    successRate: document.getElementById("kpi-success-rate"),
    avgDuration: document.getElementById("kpi-avg-duration"),
    p95Duration: document.getElementById("kpi-p95-duration"),
    avgTtft: document.getElementById("kpi-avg-ttft"),
    p95Ttft: document.getElementById("kpi-p95-ttft"),
    avgTokens: document.getElementById("kpi-avg-tokens"),
    totalTokens: document.getElementById("kpi-total-tokens"),
    totalCost: document.getElementById("kpi-total-cost"),
    runs: document.getElementById("agent-runs-tbody"),
    compareGroup: document.getElementById("compare-group-select"),
    compareRefresh: document.getElementById("compare-refresh-btn"),
    compareHeader: document.getElementById("compare-col-header"),
    compareBody: document.getElementById("compare-tbody"),
    reportCopy: document.getElementById("report-copy-btn"),
    reportRefresh: document.getElementById("report-refresh-btn"),
    report: document.getElementById("report-markdown-preview"),
  };

  async function loadMetrics() {
    const selected = getSelected();
    if (!selected) {
      dom.title.textContent = "Selecione uma entidade no chat";
      dom.runs.innerHTML = '<tr><td colspan="7" class="empty-cell">Nenhuma entidade selecionada.</td></tr>';
      return;
    }

    dom.title.textContent = `Métricas de ${selected.name || selected.id}`;
    dom.refresh.disabled = true;
    try {
      const data = await agnoApi.metrics(selected.type, selected.id, dom.days.value);
      dom.totalRuns.textContent = numberOrDash(data.total_runs);
      dom.successRate.textContent = `${numberOrDash(100 - Number(data.error_rate || 0), 1)}% de sucesso`;
      dom.avgDuration.textContent = seconds(data.avg_duration);
      dom.p95Duration.textContent = `p95 ${seconds(data.p95_duration)} · p50 ${seconds(data.p50_duration)}`;
      dom.avgTtft.textContent = milliseconds(data.avg_ttft);
      dom.p95Ttft.textContent = `p95 ${milliseconds(data.p95_ttft)}`;
      dom.avgTokens.textContent = numberOrDash(data.avg_tokens, 1);
      dom.totalTokens.textContent = `${numberOrDash(data.input_tokens_total)} entrada · ${numberOrDash(data.output_tokens_total)} saída`;
      dom.totalCost.textContent = formatCurrency(data.total_cost);
      renderRuns(data.recent_runs || []);
    } catch (error) {
      dom.runs.innerHTML = `<tr><td colspan="7" class="empty-cell error-text">${escapeHtml(error.message)}</td></tr>`;
    } finally {
      dom.refresh.disabled = false;
    }
  }

  function renderRuns(runs) {
    if (!runs.length) {
      dom.runs.innerHTML = '<tr><td colspan="7" class="empty-cell">Nenhuma execução no período.</td></tr>';
      return;
    }
    dom.runs.innerHTML = runs.map((run) => {
      const statusClass = run.status === "completed" ? "ok" : "error";
      const tokens = `${numberOrDash(run.input_tokens)} / ${numberOrDash(run.output_tokens)} / ${numberOrDash(run.total_tokens)}`;
      return `<tr>
        <td>${escapeHtml(formatDate(run.created_at, { dateStyle: "short", timeStyle: "short" }))}</td>
        <td><span class="status-badge ${statusClass}">${escapeHtml(run.status || "-")}</span></td>
        <td><code>${escapeHtml(run.model || "padrão")}</code></td>
        <td>${seconds(run.duration_seconds)}</td><td>${milliseconds(run.ttft_seconds)}</td>
        <td>${escapeHtml(tokens)}</td><td>${escapeHtml(formatCurrency(run.cost))}</td>
      </tr>`;
    }).join("");
  }

  async function loadComparison() {
    const groupBy = dom.compareGroup.value;
    dom.compareHeader.textContent = groupBy === "agent" ? "Agente" : "Modelo";
    dom.compareRefresh.disabled = true;
    dom.compareBody.innerHTML = '<tr><td colspan="8" class="empty-cell">Atualizando...</td></tr>';
    try {
      const data = await agnoApi.comparison(groupBy);
      renderComparison(data.items || []);
    } catch (error) {
      dom.compareBody.innerHTML = `<tr><td colspan="8" class="empty-cell error-text">${escapeHtml(error.message)}</td></tr>`;
    } finally {
      dom.compareRefresh.disabled = false;
    }
  }

  function renderComparison(items) {
    if (!items.length) {
      dom.compareBody.innerHTML = '<tr><td colspan="8" class="empty-cell">Sem dados para comparação.</td></tr>';
      return;
    }
    dom.compareBody.innerHTML = items.map((item) => `<tr>
      <td><strong>${escapeHtml(item.group_key || "-")}</strong></td>
      <td>${escapeHtml(item.model_provider || "-")}</td>
      <td>${numberOrDash(item.total_calls)}</td><td>${numberOrDash(item.success_rate, 1)}%</td>
      <td>${seconds(item.avg_duration)}</td><td>${milliseconds(item.avg_ttft)}</td>
      <td>${numberOrDash(item.avg_tokens, 1)}</td><td>${escapeHtml(formatCurrency(item.total_cost))}</td>
    </tr>`).join("");
  }

  async function loadReport() {
    dom.reportRefresh.disabled = true;
    dom.report.textContent = "Gerando relatório...";
    try {
      const data = await agnoApi.report();
      dom.report.textContent = data.markdown || "Relatório vazio.";
    } catch (error) {
      dom.report.textContent = `Erro: ${error.message}`;
    } finally {
      dom.reportRefresh.disabled = false;
    }
  }

  async function copyReport() {
    try {
      await copyText(dom.report.textContent);
      dom.reportCopy.textContent = "Copiado";
      window.setTimeout(() => { dom.reportCopy.textContent = "Copiar"; }, 1800);
    } catch {
      dom.reportCopy.textContent = "Falha ao copiar";
      window.setTimeout(() => { dom.reportCopy.textContent = "Copiar"; }, 1800);
    }
  }

  dom.refresh.addEventListener("click", loadMetrics);
  dom.days.addEventListener("change", loadMetrics);
  dom.compareRefresh.addEventListener("click", loadComparison);
  dom.compareGroup.addEventListener("change", loadComparison);
  dom.reportRefresh.addEventListener("click", loadReport);
  dom.reportCopy.addEventListener("click", copyReport);

  return {
    activate(viewId) {
      if (viewId === "view-metrics") loadMetrics();
      if (viewId === "view-compare") loadComparison();
      if (viewId === "view-report") loadReport();
    },
    refreshMetrics: loadMetrics,
  };
}
