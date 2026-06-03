import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, NavLink, Navigate } from "react-router-dom";

import TraceExplorer from "./components/TraceExplorer";
import CostDashboard from "./components/CostDashboard";
import HallucinationMonitor from "./components/HallucinationMonitor";
import AlertConfig from "./components/AlertConfig";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 5000 },
  },
});

const TIME_RANGES = [
  { label: "1h", hours: 1 },
  { label: "6h", hours: 6 },
  { label: "24h", hours: 24 },
  { label: "7d", hours: 168 },
];

const NAV_ITEMS = [
  { to: "/traces", label: "Traces", icon: "🔍" },
  { to: "/cost", label: "Cost", icon: "💰" },
  { to: "/hallucination", label: "Hallucination", icon: "⚠️" },
  { to: "/alerts", label: "Alerts", icon: "🔔" },
];

function Sidebar() {
  return (
    <aside className="w-56 bg-gray-900 text-gray-100 flex flex-col min-h-screen">
      <div className="px-5 py-6 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🔭</span>
          <span className="font-bold text-white text-lg">llm-scope</span>
        </div>
        <p className="text-xs text-gray-400 mt-1">LLM Observability</p>
      </div>
      <nav className="flex-1 py-4 px-3">
        {NAV_ITEMS.map(({ to, label, icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm mb-1 transition-colors ${
                isActive
                  ? "bg-violet-600 text-white"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`
            }
          >
            <span>{icon}</span>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="px-5 py-4 border-t border-gray-700 text-xs text-gray-500">
        v0.1.0
      </div>
    </aside>
  );
}

function Header({ timeRange, setTimeRange, serviceName }) {
  return (
    <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between sticky top-0 z-10">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700">{serviceName || "All Services"}</span>
      </div>
      <div className="flex gap-1">
        {TIME_RANGES.map(({ label, hours }) => (
          <button
            key={label}
            onClick={() => setTimeRange(hours)}
            className={`px-3 py-1.5 text-xs rounded ${
              timeRange === hours
                ? "bg-violet-600 text-white"
                : "border border-gray-300 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </header>
  );
}

function buildTimeRange(hours) {
  const end = new Date();
  const start = new Date(end.getTime() - hours * 60 * 60 * 1000);
  return {
    start_time: start.toISOString(),
    end_time: end.toISOString(),
  };
}

function AppInner() {
  const [timeRangeHours, setTimeRangeHours] = useState(24);
  const timeRange = buildTimeRange(timeRangeHours);

  return (
    <div className="flex min-h-screen bg-gray-50 font-sans">
      <Sidebar />
      <div className="flex-1 flex flex-col">
        <Header timeRange={timeRangeHours} setTimeRange={setTimeRangeHours} />
        <main className="flex-1 p-6 overflow-auto">
          <Routes>
            <Route path="/" element={<Navigate to="/traces" replace />} />
            <Route path="/traces" element={<TraceExplorer timeRange={timeRange} />} />
            <Route path="/cost" element={<CostDashboard timeRange={timeRange} />} />
            <Route path="/hallucination" element={<HallucinationMonitor timeRange={timeRange} />} />
            <Route path="/alerts" element={<AlertConfig />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppInner />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
