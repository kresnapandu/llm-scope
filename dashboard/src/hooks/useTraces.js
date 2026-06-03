/**
 * Custom hooks for fetching traces and metrics data.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { tracesApi, metricsApi, alertsApi } from "../api/client";

// ── Traces ────────────────────────────────────────────────────────────────────

export function useTraces(params = {}, options = {}) {
  return useQuery({
    queryKey: ["traces", params],
    queryFn: () => tracesApi.list(params),
    refetchInterval: options.autoRefresh ? 10_000 : false,
    ...options,
  });
}

export function useTrace(traceId) {
  return useQuery({
    queryKey: ["trace", traceId],
    queryFn: () => tracesApi.get(traceId),
    enabled: Boolean(traceId),
  });
}

export function useDeleteTrace() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (traceId) => tracesApi.delete(traceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["traces"] }),
  });
}

// ── Metrics ───────────────────────────────────────────────────────────────────

export function useMetricsSummary() {
  return useQuery({
    queryKey: ["metrics", "summary"],
    queryFn: metricsApi.summary,
    refetchInterval: 30_000,
  });
}

export function useCostMetrics(params = {}) {
  return useQuery({
    queryKey: ["metrics", "cost", params],
    queryFn: () => metricsApi.cost(params),
  });
}

export function useHallucinationMetrics(params = {}) {
  return useQuery({
    queryKey: ["metrics", "hallucination", params],
    queryFn: () => metricsApi.hallucination(params),
  });
}

export function useLeaderboard(params = {}) {
  return useQuery({
    queryKey: ["metrics", "leaderboard", params],
    queryFn: () => metricsApi.leaderboard(params),
  });
}

// ── Alerts ────────────────────────────────────────────────────────────────────

export function useAlerts() {
  return useQuery({
    queryKey: ["alerts"],
    queryFn: alertsApi.list,
  });
}

export function useCreateAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: alertsApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });
}

export function useUpdateAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }) => alertsApi.update(id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });
}

export function useDeleteAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: alertsApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });
}
