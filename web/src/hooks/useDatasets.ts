/** TanStack Query hooks for datasets and their records. */
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { Dataset, DatasetFilter, DatasetWithRecords, NormalizedRecord } from "../api/types";

export function useDatasets() {
  return useQuery({
    queryKey: ["datasets"],
    queryFn: () => apiClient.get<Dataset[]>("/datasets"),
  });
}

export function useDataset(datasetId: string | undefined) {
  return useQuery({
    queryKey: ["datasets", datasetId],
    queryFn: () => apiClient.get<DatasetWithRecords>(`/datasets/${datasetId}`),
    enabled: Boolean(datasetId),
  });
}

function buildRecordsQuery(filter: DatasetFilter): string {
  const params = new URLSearchParams();
  if (filter.mw_min !== undefined) params.set("mw_min", String(filter.mw_min));
  if (filter.mw_max !== undefined) params.set("mw_max", String(filter.mw_max));
  if (filter.target) params.set("target", filter.target);
  if (filter.source) params.set("source", filter.source);
  if (filter.activity_min_nm !== undefined) params.set("activity_min_nm", String(filter.activity_min_nm));
  if (filter.activity_max_nm !== undefined) params.set("activity_max_nm", String(filter.activity_max_nm));
  if (filter.limit !== undefined) params.set("limit", String(filter.limit));
  if (filter.offset !== undefined) params.set("offset", String(filter.offset));
  return params.toString();
}

export function useDatasetRecords(datasetId: string | undefined, filter: DatasetFilter = {}) {
  const query = buildRecordsQuery(filter);
  return useQuery({
    queryKey: ["datasets", datasetId, "records", filter],
    queryFn: () =>
      apiClient.get<NormalizedRecord[]>(`/datasets/${datasetId}/records${query ? `?${query}` : ""}`),
    enabled: Boolean(datasetId),
  });
}
