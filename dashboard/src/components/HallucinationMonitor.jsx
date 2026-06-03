import { useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import { useHallucinationMetrics, useTraces } from "../hooks/useTraces";

function ScoreColor(score) {
  if (score < 0.2) return { bg: "bg-green-100", text: "text-green-800", label: "Faithful" };
  if (score < 0.5) return { bg: "bg-yellow-100", text: "text-yellow-800", label: "Uncertain" };
  return { bg: "bg-red-100", text: "text-red-800", label: "Hallucinated" };
}

function ScoreBadge({ score }) {
  const color = ScoreColor(score);
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color.bg} ${color.text}`}>
      {score.toFixed(3)} — {color.label}
    </span>
  );
}

function DetailModal({ trace, onClose }) {
  if (!trace) return null;
  const attrs = trace.attributes || {};
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b">
          <h3 className="font-semibold text-gray-900">Trace Detail</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">×</button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase mb-1">Hallucination Score</p>
            <ScoreBadge score={Number(attrs["llmscope.hallucination_score"] || 0)} />
          </div>
          {attrs["gen_ai.prompt"] && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Prompt</p>
              <pre className="bg-gray-50 p-3 rounded text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap">
                {attrs["gen_ai.prompt"]}
              </pre>
            </div>
          )}
          {attrs["gen_ai.completion"] && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Completion</p>
              <pre className="bg-gray-50 p-3 rounded text-xs text-gray-700 overflow-x-auto whitespace-pre-wrap">
                {attrs["gen_ai.completion"]}
              </pre>
            </div>
          )}
          {attrs["llmscope.hallucination_reasoning"] && (
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Judge Reasoning</p>
              <p className="text-sm text-gray-600">{attrs["llmscope.hallucination_reasoning"]}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function HallucinationMonitor({ timeRange }) {
  const [filters, setFilters] = useState({ threshold: 0.5 });
  const [selectedTrace, setSelectedTrace] = useState(null);

  const { data: hallucinationData } = useHallucinationMetrics(timeRange);
  const { data: tracesData } = useTraces(
    {
      ...timeRange,
      page_size: 50,
    }
  );

  const series = hallucinationData?.data || [];
  const allTraces = (tracesData?.traces || []).filter(t => {
    const score = Number(t.attributes?.["llmscope.hallucination_score"] ?? -1);
    return score >= filters.threshold;
  });

  // Overall average score
  const allScored = (tracesData?.traces || []).filter(
    t => t.attributes?.["llmscope.hallucination_score"] !== undefined
  );
  const avgScore = allScored.length
    ? allScored.reduce((s, t) => s + Number(t.attributes["llmscope.hallucination_score"]), 0) / allScored.length
    : null;

  const scoreColor = avgScore !== null ? ScoreColor(avgScore) : null;

  // Unique models from series
  const models = [...new Set(series.map(s => s.model))];
  const COLORS = ["#7c3aed", "#0d9488", "#ea580c", "#2563eb", "#db2777"];

  return (
    <div className="space-y-6">
      {/* Summary card */}
      <div className="bg-white rounded-lg border border-gray-200 p-5 flex items-center gap-6">
        <div>
          <p className="text-sm text-gray-500">Average Hallucination Score Today</p>
          {avgScore !== null ? (
            <div className="mt-2">
              <span className={`text-4xl font-bold ${scoreColor.text.replace("text-", "text-")}`}>
                {avgScore.toFixed(3)}
              </span>
              <span className={`ml-2 inline-flex items-center px-2 py-0.5 rounded text-sm font-medium ${scoreColor.bg} ${scoreColor.text}`}>
                {scoreColor.label}
              </span>
            </div>
          ) : (
            <p className="mt-2 text-2xl font-bold text-gray-400">No data</p>
          )}
        </div>
        <div className="ml-auto text-right">
          <p className="text-sm text-gray-500">Scored Spans</p>
          <p className="text-2xl font-bold text-gray-900">{allScored.length}</p>
        </div>
      </div>

      {/* Line chart */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="font-semibold text-gray-800 mb-4">Hallucination Rate Over Time</h2>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="hour" tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip formatter={v => Number(v).toFixed(3)} />
            <Legend />
            {models.map((model, i) => (
              <Line
                key={model}
                type="monotone"
                dataKey="avg_score"
                data={series.filter(s => s.model === model)}
                name={model}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={2}
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* High-hallucination traces table */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-800">High Hallucination Traces</h2>
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <label>Threshold ≥</label>
            <input
              type="number"
              min="0" max="1" step="0.05"
              value={filters.threshold}
              onChange={e => setFilters(f => ({ ...f, threshold: parseFloat(e.target.value) }))}
              className="w-16 border border-gray-300 rounded px-2 py-1 text-sm"
            />
          </div>
        </div>
        {allTraces.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-6">
            No traces with hallucination score ≥ {filters.threshold}
          </p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b">
                {["Time", "Feature", "Model", "Score", "Prompt (snippet)", "Completion (snippet)"].map(h => (
                  <th key={h} className="pb-2 pr-4">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {allTraces.map(trace => {
                const attrs = trace.attributes || {};
                const score = Number(attrs["llmscope.hallucination_score"] || 0);
                return (
                  <tr
                    key={trace.id}
                    className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer"
                    onClick={() => setSelectedTrace(trace)}
                  >
                    <td className="py-2 pr-4 text-gray-500 whitespace-nowrap">
                      {new Date(trace.start_time).toLocaleTimeString()}
                    </td>
                    <td className="py-2 pr-4 text-gray-600">{attrs["feature"] || "—"}</td>
                    <td className="py-2 pr-4 text-gray-600 font-mono text-xs">
                      {attrs["gen_ai.request.model"] || "—"}
                    </td>
                    <td className="py-2 pr-4">
                      <ScoreBadge score={score} />
                    </td>
                    <td className="py-2 pr-4 text-gray-500 max-w-xs truncate text-xs">
                      {String(attrs["gen_ai.prompt"] || "").slice(0, 60)}…
                    </td>
                    <td className="py-2 text-gray-500 max-w-xs truncate text-xs">
                      {String(attrs["gen_ai.completion"] || "").slice(0, 60)}…
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selectedTrace && (
        <DetailModal trace={selectedTrace} onClose={() => setSelectedTrace(null)} />
      )}
    </div>
  );
}
