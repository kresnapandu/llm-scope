import { useState, useCallback } from "react";
import { useTraces } from "../hooks/useTraces";

const STATUS_COLORS = {
  OK: { bg: "bg-green-100", text: "text-green-800", dot: "bg-green-500" },
  ERROR: { bg: "bg-red-100", text: "text-red-800", dot: "bg-red-500" },
  UNSET: { bg: "bg-gray-100", text: "text-gray-600", dot: "bg-gray-400" },
};

const SPAN_COLORS = {
  "llm.": "#7c3aed",
  "retrieval.": "#0d9488",
  "tool.": "#ea580c",
  "chain.": "#64748b",
};

function getSpanColor(name) {
  for (const [prefix, color] of Object.entries(SPAN_COLORS)) {
    if (name.startsWith(prefix)) return color;
  }
  return "#64748b";
}

function StatusBadge({ status }) {
  const colors = STATUS_COLORS[status] || STATUS_COLORS.UNSET;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${colors.bg} ${colors.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
      {status}
    </span>
  );
}

function WaterfallBar({ spans, traceStart, traceDuration }) {
  if (!spans || spans.length === 0) return null;
  return (
    <div className="relative h-6 bg-gray-100 rounded overflow-hidden mt-2">
      {spans.map((span) => {
        const start = new Date(span.start_time).getTime();
        const end = new Date(span.end_time || span.start_time).getTime();
        const left = traceDuration > 0 ? ((start - traceStart) / traceDuration) * 100 : 0;
        const width = traceDuration > 0 ? Math.max(((end - start) / traceDuration) * 100, 0.5) : 0.5;
        const color = getSpanColor(span.name);
        return (
          <div
            key={span.span_id}
            title={`${span.name}\n${span.duration_ms}ms\n${JSON.stringify(span.attributes, null, 2)}`}
            className="absolute h-full opacity-80 cursor-pointer hover:opacity-100 transition-opacity"
            style={{
              left: `${left}%`,
              width: `${width}%`,
              backgroundColor: color,
            }}
          />
        );
      })}
    </div>
  );
}

function TraceRow({ trace, onExpand, isExpanded, childSpans }) {
  const attrs = trace.attributes || {};
  const model = attrs["gen_ai.request.model"] || "—";
  const cost = attrs["llmscope.cost_usd"];
  const tokens = (attrs["gen_ai.usage.input_tokens"] || 0) + (attrs["gen_ai.usage.output_tokens"] || 0);

  const childList = childSpans?.spans || [];
  const traceStart = childList.length > 0
    ? Math.min(...childList.map(s => new Date(s.start_time).getTime()))
    : new Date(trace.start_time).getTime();
  const traceEnd = childList.length > 0
    ? Math.max(...childList.map(s => new Date(s.end_time || s.start_time).getTime()))
    : new Date(trace.end_time || trace.start_time).getTime();
  const traceDuration = traceEnd - traceStart;

  return (
    <>
      <tr
        className="hover:bg-gray-50 cursor-pointer border-b border-gray-100"
        onClick={onExpand}
      >
        <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">
          {new Date(trace.start_time).toLocaleTimeString()}
        </td>
        <td className="px-4 py-3 text-sm font-mono text-gray-900 max-w-xs truncate">
          {trace.name}
        </td>
        <td className="px-4 py-3 text-sm text-gray-600">{trace.service_name}</td>
        <td className="px-4 py-3 text-sm text-gray-600">{model}</td>
        <td className="px-4 py-3 text-sm text-gray-600">{trace.duration_ms}ms</td>
        <td className="px-4 py-3 text-sm text-gray-600">{tokens.toLocaleString()}</td>
        <td className="px-4 py-3 text-sm text-gray-600">
          {cost !== undefined ? `$${Number(cost).toFixed(6)}` : "—"}
        </td>
        <td className="px-4 py-3">
          <StatusBadge status={trace.status} />
        </td>
      </tr>
      {isExpanded && (
        <tr className="bg-gray-50">
          <td colSpan={8} className="px-6 py-4">
            <div className="text-xs text-gray-500 mb-1 font-medium">Waterfall</div>
            <WaterfallBar
              spans={[trace, ...childList]}
              traceStart={traceStart}
              traceDuration={traceDuration || 1}
            />
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              {Object.entries(attrs)
                .filter(([k]) => k.startsWith("gen_ai.") || k.startsWith("llmscope."))
                .map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <span className="text-gray-400 font-mono">{k}:</span>
                    <span className="text-gray-700 truncate">{String(v)}</span>
                  </div>
                ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function TraceExplorer({ timeRange }) {
  const [filters, setFilters] = useState({});
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [expandedSpans, setExpandedSpans] = useState({});

  const { data, isLoading, error } = useTraces(
    { ...filters, ...timeRange, page, page_size: 50 },
    { autoRefresh }
  );

  const traces = data?.traces || [];
  const total = data?.total || 0;
  const pages = data?.pages || 1;

  const handleFilterChange = useCallback((key, value) => {
    setFilters(f => ({ ...f, [key]: value || undefined }));
    setPage(1);
  }, []);

  const handleExpand = useCallback(async (trace) => {
    if (expandedId === trace.trace_id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(trace.trace_id);
    if (!expandedSpans[trace.trace_id]) {
      try {
        const { tracesApi } = await import("../api/client");
        const spans = await tracesApi.getSpans(trace.trace_id);
        setExpandedSpans(s => ({ ...s, [trace.trace_id]: spans }));
      } catch (_) {}
    }
  }, [expandedId, expandedSpans]);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap gap-3 bg-white p-4 rounded-lg border border-gray-200">
        {[
          { key: "service_name", label: "Service" },
          { key: "model", label: "Model" },
          { key: "feature", label: "Feature" },
          { key: "user_id", label: "User ID" },
        ].map(({ key, label }) => (
          <input
            key={key}
            type="text"
            placeholder={label}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 w-36"
            onChange={e => handleFilterChange(key, e.target.value)}
          />
        ))}
        <select
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
          onChange={e => handleFilterChange("status", e.target.value)}
        >
          <option value="">All Status</option>
          <option value="OK">OK</option>
          <option value="ERROR">ERROR</option>
          <option value="UNSET">UNSET</option>
        </select>
        <input
          type="text"
          placeholder="Search..."
          className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 flex-1 min-w-32"
          onChange={e => handleFilterChange("search", e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm text-gray-600 ml-auto">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={e => setAutoRefresh(e.target.checked)}
            className="rounded"
          />
          Auto-refresh
        </label>
      </div>

      {/* Table */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-500">Loading traces…</div>
        ) : error ? (
          <div className="p-8 text-center text-red-500">{error.message}</div>
        ) : traces.length === 0 ? (
          <div className="p-8 text-center text-gray-400">No traces found</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                {["Time", "Name", "Service", "Model", "Duration", "Tokens", "Cost", "Status"].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {traces.map(trace => (
                <TraceRow
                  key={trace.id}
                  trace={trace}
                  isExpanded={expandedId === trace.trace_id}
                  childSpans={expandedSpans[trace.trace_id]}
                  onExpand={() => handleExpand(trace)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-600">
          <span>{total.toLocaleString()} traces</span>
          <div className="flex gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50"
            >
              ← Prev
            </button>
            <span className="px-3 py-1">{page} / {pages}</span>
            <button
              disabled={page >= pages}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-50"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
