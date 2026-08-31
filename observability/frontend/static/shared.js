export async function fetchJson(url, options = {}) {
  const response = await fetch(url, { cache: "no-store", ...options });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function formatDate(value, options = {}) {
  if (!value) return "sem data";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("pt-BR", options);
}

export function formatTime(value) {
  if (!value) return "agora";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "agora";
  return date.toLocaleTimeString("pt-BR");
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return "sem dado";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (Math.abs(value) >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ${units[index]}`;
}

export function formatCurrency(value) {
  if (!Number.isFinite(value)) return "sem dado";
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: Math.abs(value) < 1 ? 6 : 2,
  });
}

const formatters = {
  count: (value) => Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 0 }),
  rps: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}/s`,
  percent: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`,
  seconds: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 3 })}s`,
  bytes: (value) => formatBytes(Number(value)),
  bytes_per_second: (value) => `${formatBytes(Number(value))}/s`,
  chars: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} chars`,
  currency: (value) => formatCurrency(Number(value)),
  currency_per_minute: (value) => `${formatCurrency(Number(value))}/min`,
  per_minute: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}/min`,
  tokens: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} tokens`,
  tokens_per_second: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} tok/s`,
  watts: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} W`,
  celsius: (value) => `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} °C`,
  state: (value) => Number(value) >= 1 ? "online" : "offline",
};

export function formatMetric(value, unit = "count") {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "sem dado";
  }
  return (formatters[unit] || formatters.count)(value);
}

export function shortMetric(value, unit = "count") {
  if (!Number.isFinite(value)) return "-";
  if (unit === "percent") return `${Math.round(value)}%`;
  if (unit === "bytes_per_second" || unit === "bytes") return formatBytes(value);
  if (unit.startsWith("currency")) return formatCurrency(value);
  return Number(value).toLocaleString("pt-BR", {
    maximumFractionDigits: Math.abs(value) < 10 ? 1 : 0,
  });
}

export function shortId(value, length = 12) {
  const text = String(value || "");
  if (text.length <= length) return text || "-";
  return `${text.slice(0, length)}…`;
}

export async function copyText(value) {
  await navigator.clipboard.writeText(String(value || ""));
}

