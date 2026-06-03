/**
 * llm-scope API client.
 * All requests target the FastAPI backend (VITE_API_URL or localhost:8000).
 */

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function apiFetch(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  try {
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
    if (!response.ok) {
      let errorMsg = `HTTP ${response.status}`;
      try {
        const errBody = await response.json();
        errorMsg = errBody.detail || errBody.message || errorMsg;
      } catch (_) {}
      throw new Error(errorMsg);
    }
    return response.json();
  } catch (err) {
    if (err instanceof Error) throw err;
    throw new Error(String(err));
  }
}

function toQuery(params) {
  const filtered = Object.fromEntries(
    Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );
  return new URLSearchParams(filtered).toString();
}

// ── Traces ────────────────────────────────────────────────────────────────────

export const tracesApi = {
  list: (params = {}) => {
    const q = toQuery(params);
    return apiFetch(`/api/traces${q ? "?" + q : ""}`);
  },
  get: (traceId) => apiFetch(`/api/traces/${traceId}`),
  getSpans: (traceId) => apiFetch(`/api/traces/${traceId}/spans`),
  delete: (traceId) =>
    apiFetch(`/api/traces/${traceId}`, { method: "DELETE" }),
};

// ── Metrics ───────────────────────────────────────────────────────────────────

export const metricsApi = {
  cost: (params = {}) => {
    const q = toQuery(params);
    return apiFetch(`/api/metrics/cost${q ? "?" + q : ""}`);
  },
  hallucination: (params = {}) => {
    const q = toQuery(params);
    return apiFetch(`/api/metrics/hallucination${q ? "?" + q : ""}`);
  },
  summary: () => apiFetch("/api/metrics/summary"),
  leaderboard: (params = {}) => {
    const q = toQuery(params);
    return apiFetch(`/api/metrics/leaderboard${q ? "?" + q : ""}`);
  },
};

// ── Alerts ────────────────────────────────────────────────────────────────────

export const alertsApi = {
  list: () => apiFetch("/api/alerts"),
  create: (body) =>
    apiFetch("/api/alerts", { method: "POST", body: JSON.stringify(body) }),
  update: (id, body) =>
    apiFetch(`/api/alerts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  delete: (id) => apiFetch(`/api/alerts/${id}`, { method: "DELETE" }),
};

// ── Judge ─────────────────────────────────────────────────────────────────────

export const judgeApi = {
  score: (body) =>
    apiFetch("/api/judge", { method: "POST", body: JSON.stringify(body) }),
};

// ── Health ────────────────────────────────────────────────────────────────────

export const healthApi = {
  check: () => apiFetch("/health"),
};
