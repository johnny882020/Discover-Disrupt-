/**
 * TanStack Query hooks for triggering, polling and cancelling pipeline runs.
 *
 * The API only queues a run; its run worker executes it in the background,
 * so the UI learns about progress by polling.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { PipelineRun, RunPipelineRequest } from "../api/types";

/**
 * In-progress runs are re-polled; terminal runs stop refetching. A
 * succeeded, failed or cancelled run never changes again, so polling it would
 * only add load. `pending` includes a run waiting to resume after an
 * interruption, which the worker will pick up again.
 */
const ACTIVE_STATUSES = new Set(["pending", "running"]);

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: () => apiClient.get<PipelineRun[]>("/pipelines/runs"),
    refetchInterval: (query) => {
      const runs = query.state.data;
      // Slower than a single run's poll: the list is a background overview.
      return runs?.some((run) => ACTIVE_STATUSES.has(run.status)) ? 3000 : false;
    },
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: ["runs", runId],
    queryFn: () => apiClient.get<PipelineRun>(`/pipelines/runs/${runId}`),
    enabled: Boolean(runId),
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? 2000 : false),
  });
}

export function useTriggerRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RunPipelineRequest) => apiClient.post<PipelineRun>("/pipelines/run", body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
      void queryClient.invalidateQueries({ queryKey: ["datasets"] });
    },
  });
}

export function useCancelRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => apiClient.post<PipelineRun>(`/pipelines/runs/${runId}/cancel`),
    onSuccess: (run) => {
      // Show the answer now (a pending run is cancelled at once) instead of
      // waiting for the next poll.
      queryClient.setQueryData(["runs", run.id], run);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}
