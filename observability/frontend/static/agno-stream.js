function normalizeEvent(chunk) {
  if (!chunk || typeof chunk !== "object" || !("data" in chunk)) return chunk;
  let data = chunk.data;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      data = { content: data };
    }
  }
  return { event: chunk.event, ...(data || {}) };
}

function consumeLines(buffer, onEvent, flush = false) {
  const lines = buffer.split(/\r?\n/);
  const remainder = flush ? "" : lines.pop() || "";
  for (const line of lines) {
    const candidate = line.trim().replace(/^data:\s*/, "");
    if (!candidate || candidate === "[DONE]") continue;
    onEvent(normalizeEvent(JSON.parse(candidate)));
  }
  if (flush && remainder.trim()) {
    onEvent(normalizeEvent(JSON.parse(remainder.trim().replace(/^data:\s*/, ""))));
  }
  return remainder;
}

export async function readEventStream(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = consumeLines(buffer, onEvent);
  }

  buffer += decoder.decode();
  consumeLines(`${buffer}\n`, onEvent, true);
}
