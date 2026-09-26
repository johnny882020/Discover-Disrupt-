/** TanStack Query hooks for managing an organization's members and invitations. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type {
  Invitation,
  InvitationCreate,
  InvitationCreated,
  PasswordResetCreated,
  Role,
  User,
} from "../api/types";

const MEMBERS = ["team", "members"] as const;
const INVITATIONS = ["team", "invitations"] as const;

export function useMembers(enabled = true) {
  return useQuery({
    queryKey: MEMBERS,
    queryFn: () => apiClient.get<User[]>("/auth/members"),
    enabled,
  });
}

export function usePendingInvitations(enabled = true) {
  return useQuery({
    queryKey: INVITATIONS,
    queryFn: () => apiClient.get<Invitation[]>("/auth/invitations"),
    enabled,
  });
}

export function useInvite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: InvitationCreate) => apiClient.post<InvitationCreated>("/auth/invitations", body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: INVITATIONS }),
  });
}

export function useRevokeInvitation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) => apiClient.del<void>(`/auth/invitations/${invitationId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: INVITATIONS }),
  });
}

export function useChangeRole() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      apiClient.patch<User>(`/auth/members/${userId}`, { role }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: MEMBERS }),
  });
}

export function useRemoveMember() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (userId: string) => apiClient.del<void>(`/auth/members/${userId}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: MEMBERS }),
  });
}

export function useIssuePasswordReset() {
  return useMutation({
    mutationFn: (userId: string) =>
      apiClient.post<PasswordResetCreated>(`/auth/members/${userId}/password-reset`),
  });
}
