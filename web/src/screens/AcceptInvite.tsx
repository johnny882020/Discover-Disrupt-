/**
 * Invitation screen (`/invite#token=…`): shows who the invitation is for and
 * lets the invitee choose a password, which creates their account and signs
 * them in.
 */
import type { InvitationPreview } from "../api/types";
import { TokenPasswordScreen } from "../auth/TokenPasswordScreen";
import { useSession } from "../auth/useSession";

export function AcceptInvite(): React.JSX.Element {
  const { acceptInvitation } = useSession();
  return (
    <TokenPasswordScreen<InvitationPreview>
      title="Accept your invitation"
      previewPath="/auth/invitations/preview"
      redeem={acceptInvitation}
      describe={(preview) => (
        <>
          You&apos;ve been invited to join <strong>{preview.org_name}</strong> as{" "}
          {preview.role === "admin" ? "an admin" : "a member"}. Choose a password for{" "}
          <strong>{preview.email}</strong>.
        </>
      )}
      invalidHint="Invitation links work once and expire. Ask your organization's admin for a new one."
      submitLabel="Create account"
      pendingLabel="Creating your account…"
    />
  );
}
