import { useState } from "react";
import { useAlerts, useCreateAlert, useUpdateAlert, useDeleteAlert } from "../hooks/useTraces";

const ALERT_TYPES = [
  { value: "cost_spike", label: "Cost Spike", description: "Alert when cost exceeds threshold (USD per batch)" },
  { value: "error_rate", label: "Error Rate", description: "Alert when error rate exceeds threshold (0–1)" },
  { value: "high_hallucination", label: "High Hallucination", description: "Alert when avg hallucination score exceeds threshold (0–1)" },
];

function AlertForm({ initial, onSubmit, onCancel }) {
  const [form, setForm] = useState(initial || {
    name: "",
    type: "cost_spike",
    threshold: 1.0,
    window_minutes: 60,
    slack_webhook: "",
    webhook_url: "",
    enabled: true,
  });

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  return (
    <form
      onSubmit={e => { e.preventDefault(); onSubmit(form); }}
      className="bg-gray-50 rounded-lg border border-gray-200 p-5 space-y-4"
    >
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
          <input
            required
            type="text"
            value={form.name}
            onChange={e => set("name", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
            placeholder="High Cost Alert"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
          <select
            value={form.type}
            onChange={e => set("type", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          >
            {ALERT_TYPES.map(t => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <p className="text-xs text-gray-400 mt-1">
            {ALERT_TYPES.find(t => t.value === form.type)?.description}
          </p>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Threshold</label>
          <input
            required
            type="number"
            step="any"
            value={form.threshold}
            onChange={e => set("threshold", parseFloat(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Window (minutes)</label>
          <input
            type="number"
            value={form.window_minutes}
            onChange={e => set("window_minutes", parseInt(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
          />
        </div>
        <div className="col-span-2">
          <label className="block text-sm font-medium text-gray-700 mb-1">Slack Webhook URL</label>
          <input
            type="url"
            value={form.slack_webhook || ""}
            onChange={e => set("slack_webhook", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
            placeholder="https://hooks.slack.com/services/..."
          />
        </div>
        <div className="col-span-2">
          <label className="block text-sm font-medium text-gray-700 mb-1">Generic Webhook URL</label>
          <input
            type="url"
            value={form.webhook_url || ""}
            onChange={e => set("webhook_url", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
            placeholder="https://your-server.com/webhook"
          />
        </div>
      </div>
      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          className="px-4 py-2 bg-violet-600 text-white text-sm rounded hover:bg-violet-700"
        >
          Save Rule
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-2 border border-gray-300 text-sm rounded hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function AlertConfig() {
  const [showForm, setShowForm] = useState(false);

  const { data, isLoading } = useAlerts();
  const createAlert = useCreateAlert();
  const updateAlert = useUpdateAlert();
  const deleteAlert = useDeleteAlert();

  const rules = data?.rules || [];

  const handleCreate = async (form) => {
    await createAlert.mutateAsync(form);
    setShowForm(false);
  };

  const handleToggle = async (rule) => {
    await updateAlert.mutateAsync({ id: rule.id, enabled: !rule.enabled });
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this alert rule?")) return;
    await deleteAlert.mutateAsync(id);
  };

  const typeLabel = (type) => ALERT_TYPES.find(t => t.value === type)?.label || type;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Alert Rules</h1>
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 bg-violet-600 text-white text-sm rounded hover:bg-violet-700"
        >
          + New Rule
        </button>
      </div>

      {showForm && (
        <AlertForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}

      {isLoading ? (
        <div className="text-center text-gray-400 py-8">Loading…</div>
      ) : rules.length === 0 && !showForm ? (
        <div className="text-center text-gray-400 py-12 bg-white rounded-lg border border-gray-200">
          <p className="text-lg">No alert rules yet.</p>
          <p className="text-sm mt-1">Create one to get notified of cost spikes, errors, or hallucinations.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {rules.map(rule => (
            <div
              key={rule.id}
              className={`bg-white rounded-lg border p-5 flex items-center gap-4 ${
                rule.enabled ? "border-gray-200" : "border-gray-100 opacity-60"
              }`}
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{rule.name}</span>
                  <span className="text-xs px-2 py-0.5 bg-violet-50 text-violet-700 rounded">
                    {typeLabel(rule.type)}
                  </span>
                  {!rule.enabled && (
                    <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded">Disabled</span>
                  )}
                </div>
                <p className="text-sm text-gray-500 mt-1">
                  Threshold: <strong>{rule.threshold}</strong> · Window: {rule.window_minutes}min
                  {rule.slack_webhook && " · Slack"}
                  {rule.webhook_url && " · Webhook"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleToggle(rule)}
                  className={`text-sm px-3 py-1 rounded border ${
                    rule.enabled
                      ? "border-orange-300 text-orange-600 hover:bg-orange-50"
                      : "border-green-300 text-green-600 hover:bg-green-50"
                  }`}
                >
                  {rule.enabled ? "Disable" : "Enable"}
                </button>
                <button
                  onClick={() => handleDelete(rule.id)}
                  className="text-sm px-3 py-1 rounded border border-red-300 text-red-600 hover:bg-red-50"
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
