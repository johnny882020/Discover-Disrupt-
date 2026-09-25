/** TanStack Query hooks for triggering and polling pipeline runs. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { PipelineRun, RunPipelineRequest } from "../api/types";

/** In-progress runs are re-polled; terminal runs stop refetching. */
const ACTIVE_STATUSES = new Set(["pending", "running"]);

export function useRuns() {
  return useQuery({
    queryKey: ["runs"],
    queryFn: () => apiClient.get<PipelineRun[]>("/pipelines/runs"),
    refetchInterval: (query) => {
      const runs = query.state.data;
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
