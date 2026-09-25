/** TanStack Query hook for a dataset's quality report. */
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { QualityReport } from "../api/types";

export function useQualityReport(datasetId: string | undefined) {
  return useQuery({
    queryKey: ["datasets", datasetId, "quality-report"],
    queryFn: () => apiClient.get<QualityReport>(`/datasets/${datasetId}/quality-report`),
    enabled: Boolean(datasetId),
  });
}
