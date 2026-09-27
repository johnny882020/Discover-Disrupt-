/** TanStack Query hook for a dataset's hit/lead assessment. */
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { DatasetAssessment } from "../api/types";

export function useAssessment(datasetId: string | undefined) {
  return useQuery({
    queryKey: ["datasets", datasetId, "assessment"],
    queryFn: () => apiClient.get<DatasetAssessment>(`/datasets/${datasetId}/assessment`),
    enabled: Boolean(datasetId),
  });
}
