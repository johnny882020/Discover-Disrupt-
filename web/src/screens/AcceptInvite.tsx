/**
 * Invitation screen (`/invite#token=…`): shows who the invitation is for and
 * lets the invitee choose a password, which creates their account and signs
 * them in.
 *
 * The token travels in the URL fragment, which browsers never send to a
 * server, and is removed from the address bar as soon as it is read.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { apiClient } from "../api/client";
import type { InvitationPreview } from "../api/types";
import { authErrorMessage } from "../auth/errorMessage";
import { MAX_PASSWORD_LENGTH, PASSWORD_HINT, newPasswordProblem } from "../auth/passwordPolicy";
import { useSession } from "../auth/useSession";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { TextField } from "../design-system/TextField";

function tokenFromHash(hash: string): string | null {
  return new URLSearchParams(hash.replace(/^#/, "")).get("token");
}

export function AcceptInvite(): React.JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const { acceptInvitation } = useSession();
  const [token] = useState<string | null>(() => tokenFromHash(location.hash));
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (location.hash) {
      navigate({ pathname: location.pathname, search: location.search }, { replace: true });
    }
  }, [location.hash, location.pathname, location.search, navigate]);

  const preview = useQuery({
    queryKey: ["invitation-preview", token],
    queryFn: () => apiClient.post<InvitationPreview>("/auth/invitations/preview", { token }, null),
    enabled: token !== null,
    retry: false,
    staleTime: Infinity,
  });

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!token) {
      return;
    }
    const problem = newPasswordProblem(password, confirmation);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setPending(true);
    try {
      await acceptInvitation(token, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(authErrorMessage(err));
      setPending(false);
    }
  }

  let body: React.JSX.Element;
  if (!token || preview.isError) {
    body = (
      <div className="flex flex-col gap-3">
        <p role="alert" className="text-sm text-danger">
          {token ? authErrorMessage(preview.error) : "This invitation link is incomplete."}
        </p>
        <p className="text-sm text-ink/60 dark:text-paper/60">
          Invitation links work once and expire. Ask your organization&apos;s admin for a new one.
        </p>
        <Link to="/" className="text-sm text-accent hover:underline">
          Go to sign in
        </Link>
      </div>
    );
  } else if (!preview.data) {
    body = <p className="text-sm text-ink/60 dark:text-paper/60">Checking your invitation…</p>;
  } else {
    body = (
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <p className="text-sm text-ink/70 dark:text-paper/70">
          You&apos;ve been invited to join <strong>{preview.data.org_name}</strong> as{" "}
          {preview.data.role === "admin" ? "an admin" : "a member"}. Choose a password for{" "}
          <strong>{preview.data.email}</strong>.
        </p>
        {/* Lets password managers associate the new password with the account. */}
        <input type="email" name="email" autoComplete="username" value={preview.data.email} readOnly hidden />
        <TextField
          label="New password"
          name="new-password"
          type="password"
          autoComplete="new-password"
          required
          maxLength={MAX_PASSWORD_LENGTH}
          hint={PASSWORD_HINT}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <TextField
          label="Confirm password"
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
        <Button type="submit" disabled={pending || password === "" || confirmation === ""}>
          {pending ? "Creating your account…" : "Create account"}
        </Button>
      </form>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4 text-ink dark:bg-ink dark:text-paper">
      <Card className="w-full max-w-sm">
        <div className="flex flex-col gap-4">
          <h1 className="font-display text-2xl">Accept your invitation</h1>
          {body}
        </div>
      </Card>
    </div>
  );
}
