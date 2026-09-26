/** Account screen: who is signed in, and (for users) a password change. */
import { useState, type FormEvent } from "react";
import { apiClient } from "../api/client";
import type { PasswordChange } from "../api/types";
import { authErrorMessage } from "../auth/errorMessage";
import { MAX_PASSWORD_LENGTH, PASSWORD_HINT, newPasswordProblem } from "../auth/passwordPolicy";
import { useSession } from "../auth/useSession";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { TextField } from "../design-system/TextField";

function ChangePasswordForm(): React.JSX.Element {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setDone(false);
    const problem = newPasswordProblem(next, confirmation);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setPending(true);
    try {
      const body: PasswordChange = { current_password: current, new_password: next };
      await apiClient.post<void>("/auth/password", body);
      setCurrent("");
      setNext("");
      setConfirmation("");
      setDone(true);
    } catch (err) {
      setError(authErrorMessage(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 sm:max-w-md">
      <h2 className="font-display text-xl">Change password</h2>
      <TextField
        label="Current password"
        name="current-password"
        type="password"
        autoComplete="current-password"
        required
        value={current}
        onChange={(e) => setCurrent(e.target.value)}
      />
      <TextField
        label="New password"
        name="new-password"
        type="password"
        autoComplete="new-password"
        required
        maxLength={MAX_PASSWORD_LENGTH}
        hint={PASSWORD_HINT}
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
      <TextField
        label="Confirm new password"
        name="confirm-password"
        type="password"
        autoComplete="new-password"
        required
        maxLength={MAX_PASSWORD_LENGTH}
        value={confirmation}
        onChange={(e) => setConfirmation(e.target.value)}
      />
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      {done ? (
        <p role="status" className="text-sm text-success">
          Password changed. You&apos;ve been signed out everywhere else.
        </p>
      ) : null}
      <Button type="submit" disabled={pending || current === "" || next === "" || confirmation === ""}>
        {pending ? "Saving…" : "Change password"}
      </Button>
    </form>
  );
}

export function Account(): React.JSX.Element {
  const { org } = useSession();
  const isUser = org?.principal === "user";

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-3xl">Account</h1>
      <Card>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-ink/60 dark:text-paper/60">Organization</dt>
          <dd>{org?.org_name}</dd>
          <dt className="text-ink/60 dark:text-paper/60">Signed in as</dt>
          <dd>{isUser ? org.email : "Organization API key"}</dd>
          <dt className="text-ink/60 dark:text-paper/60">Role</dt>
          <dd className="capitalize">{org?.role}</dd>
        </dl>
      </Card>
      {isUser ? (
        <Card>
          <ChangePasswordForm />
        </Card>
      ) : (
        <Card>
          <p className="text-sm text-ink/70 dark:text-paper/70">
            You&apos;re signed in with an API key, which has no password. To use the web app with
            your own account, ask an admin for an invitation.
          </p>
        </Card>
      )}
    </div>
  );
}
