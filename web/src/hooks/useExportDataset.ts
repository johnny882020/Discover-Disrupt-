/**
 * Triggers a dataset export download via the API.
 *
 * The file is fetched with the credential header and saved from a Blob,
 * because a plain link to the export URL could not authenticate.
 */
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { ExportFormat } from "../api/types";

interface ExportArgs {
  datasetId: string;
  format: ExportFormat;
  filename: string;
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function useExportDataset() {
  return useMutation({
    mutationFn: async ({ datasetId, format, filename }: ExportArgs) => {
      const blob = await apiClient.getBlob(`/datasets/${datasetId}/export?format=${format}`);
      downloadBlob(blob, filename);
    },
  });
}
