/**
 * Password-reset screen (`/reset#token=…`): the user chooses a new password,
 * which signs them in and ends every other session of theirs.
 */
import type { PasswordResetPreview } from "../api/types";
import { TokenPasswordScreen } from "../auth/TokenPasswordScreen";
import { useSession } from "../auth/useSession";

export function ResetPassword(): React.JSX.Element {
  const { resetPassword } = useSession();
  return (
    <TokenPasswordScreen<PasswordResetPreview>
      title="Reset your password"
      previewPath="/auth/password-reset/preview"
      redeem={resetPassword}
      describe={(preview) => (
        <>
          Choose a new password for <strong>{preview.email}</strong> at{" "}
          <strong>{preview.org_name}</strong>. You&apos;ll be signed out everywhere else.
        </>
      )}
      invalidHint="Reset links work once and expire after 24 hours. Ask your organization's admin for a new one."
      submitLabel="Set new password"
      pendingLabel="Saving…"
    />
  );
}
