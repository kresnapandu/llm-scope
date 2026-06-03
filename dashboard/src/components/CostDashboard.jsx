import { useState } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { useMetricsSummary, useCostMetrics, useLeaderboard } from "../hooks/useTraces";

function MetricCard({ label, value, sub }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function formatCost(v) {
  if (v === null || v === undefined) return "$0";
  const n = Number(v);
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(6)}`;
  if (n < 1) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

export default function CostDashboard({ timeRange }) {
  const [granularity, setGranularity] = useState("hourly");
  const [groupBy, setGroupBy] = useState("model");

  const { data: summary } = useMetricsSummary();
  const { data: costData } = useCostMetrics({ granularity, group_by: groupBy, ...timeRange });
  const { data: leaderboard } = useLeaderboard({ metric: "cost" });

  const costSeries = costData?.data || [];
  const leaders = leaderboard?.leaderboard || [];
  const topModels = summary?.top_models || [];
  const topFeatures = summary?.top_features || [];

  return (
    <div className="space-y-6">
      {/* Metric cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Cost Today"
          value={formatCost(summary?.total_cost_today)}
        />
        <MetricCard
          label="Total Calls Today"
          value={(summary?.total_calls_today || 0).toLocaleString()}
        />
        <MetricCard
          label="Avg Latency"
          value={`${summary?.avg_latency_ms || 0}ms`}
        />
        <MetricCard
          label="Cost / Call"
          value={
            summary?.total_calls_today
              ? formatCost((summary.total_cost_today || 0) / summary.total_calls_today)
              : "$0"
          }
        />
      </div>

      {/* Cost over time */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-800">Cost Over Time</h2>
          <div className="flex gap-2">
            {["hourly", "daily"].map(g => (
              <button
                key={g}
                onClick={() => setGranularity(g)}
                className={`px-3 py-1 text-xs rounded ${
                  granularity === g
                    ? "bg-violet-600 text-white"
                    : "border border-gray-300 text-gray-600 hover:bg-gray-50"
                }`}
              >
                {g}
              </button>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={costSeries}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
            <YAxis tickFormatter={v => `$${v.toFixed(4)}`} tick={{ fontSize: 11 }} />
            <Tooltip formatter={v => formatCost(v)} />
            <Line
              type="monotone"
              dataKey="total_cost_usd"
              stroke="#7c3aed"
              strokeWidth={2}
              dot={false}
              name="Cost"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Cost by model */}
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Cost by Model</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={topModels.slice(0, 5)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="model" tick={{ fontSize: 10 }} />
              <YAxis tickFormatter={v => `$${v.toFixed(3)}`} tick={{ fontSize: 10 }} />
              <Tooltip formatter={v => formatCost(v)} />
              <Bar dataKey="cost" fill="#7c3aed" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Cost by feature */}
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Cost by Feature</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={topFeatures.slice(0, 10)} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis type="number" tickFormatter={v => `$${v.toFixed(4)}`} tick={{ fontSize: 10 }} />
              <YAxis type="category" dataKey="feature" tick={{ fontSize: 10 }} width={100} />
              <Tooltip formatter={v => formatCost(v)} />
              <Bar dataKey="cost" fill="#0d9488" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* User leaderboard */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h2 className="font-semibold text-gray-800 mb-4">Top Users by Cost Today</h2>
        {leaders.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-6">No data yet</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-gray-500 uppercase tracking-wide border-b">
                <th className="pb-2 pr-4">#</th>
                <th className="pb-2 pr-4">User</th>
                <th className="pb-2 pr-4">Feature</th>
                <th className="pb-2 text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {leaders.map((row, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="py-2 pr-4 text-gray-400">{i + 1}</td>
                  <td className="py-2 pr-4 font-mono text-gray-700">{row.user_id || "—"}</td>
                  <td className="py-2 pr-4 text-gray-500">{row.feature || "—"}</td>
                  <td className="py-2 text-right font-medium text-gray-900">
                    {formatCost(row.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
