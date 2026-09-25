/** TanStack Query hook for a dataset's GenMol enrichment results. */
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { EnrichmentResponse } from "../api/types";

export function useEnrichment(datasetId: string | undefined) {
  return useQuery({
    queryKey: ["datasets", datasetId, "enrichment"],
    queryFn: () => apiClient.get<EnrichmentResponse>(`/datasets/${datasetId}/enrichment`),
    enabled: Boolean(datasetId),
  });
}
