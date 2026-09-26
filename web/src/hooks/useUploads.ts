/** TanStack Query hooks for uploads and saved column mappings. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { MappingTemplate, MappingTemplateCreate, UploadPreview } from "../api/types";

const TEMPLATES = ["mapping-templates"] as const;

export function useUploadFile() {
  return useMutation({
    mutationFn: (file: File) => apiClient.upload<UploadPreview>("/uploads", file),
  });
}

export function useMappingTemplates() {
  return useQuery({
    queryKey: TEMPLATES,
    queryFn: () => apiClient.get<MappingTemplate[]>("/mapping-templates"),
  });
}

export function useSaveTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: MappingTemplateCreate) => apiClient.post<MappingTemplate>("/mapping-templates", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: TEMPLATES }),
  });
}

export function useDeleteTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) => apiClient.del<void>(`/mapping-templates/${templateId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: TEMPLATES }),
  });
}
