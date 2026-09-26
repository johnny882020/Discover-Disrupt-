/**
 * Team screen: organization admins invite colleagues by email. The one-time
 * invitation link is shown here to be sent to the invitee.
 */
import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { apiClient } from "../api/client";
import type { InvitationCreate, InvitationCreated, Role } from "../api/types";
import { authErrorMessage } from "../auth/errorMessage";
import { useSession } from "../auth/useSession";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { TextField } from "../design-system/TextField";

export function Team(): React.JSX.Element {
  const { org } = useSession();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [copied, setCopied] = useState(false);
  const invite = useMutation({
    mutationFn: (body: InvitationCreate) => apiClient.post<InvitationCreated>("/auth/invitations", body),
    onSuccess: () => {
      setEmail("");
      setCopied(false);
    },
  });

  if (org?.role !== "admin") {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="font-display text-3xl">Team</h1>
        <Card>
          <p className="text-sm">Only your organization&apos;s admins can invite new members.</p>
        </Card>
      </div>
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    invite.mutate({ email: email.trim(), role });
  }

  async function copyLink(link: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-display text-3xl">Team</h1>
        <p className="mt-1 text-sm text-ink/60 dark:text-paper/60">
          Invite a colleague to {org.org_name}. They choose their own password when they accept.
        </p>
      </div>
      <Card>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 sm:max-w-md">
          <TextField
            label="Email"
            name="invite-email"
            type="email"
            autoComplete="off"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium">Role</span>
            <select
              name="invite-role"
              value={role}
              onChange={(e) => setRole(e.target.value as Role)}
              className="rounded border border-ink/15 bg-transparent px-3 py-2 text-sm dark:border-paper/20"
            >
              <option value="member">Member — can run pipelines and view data</option>
              <option value="admin">Admin — can also invite others</option>
            </select>
          </label>
          {invite.isError ? (
            <p role="alert" className="text-sm text-danger">
              {authErrorMessage(invite.error)}
            </p>
          ) : null}
          <Button type="submit" disabled={invite.isPending || email.trim() === ""}>
            {invite.isPending ? "Creating invitation…" : "Create invitation"}
          </Button>
        </form>
      </Card>
      {invite.data ? (
        <Card>
          <div className="flex flex-col gap-3">
            <h2 className="font-display text-xl">Invitation for {invite.data.email}</h2>
            <p className="text-sm text-ink/70 dark:text-paper/70">
              Send this link to {invite.data.email}. It works once, expires on{" "}
              {new Date(invite.data.expires_at).toLocaleString()}, and is not shown again.
            </p>
            <div className="flex gap-2">
              <input
                aria-label="Invitation link"
                readOnly
                value={invite.data.accept_url}
                onFocus={(e) => e.currentTarget.select()}
                className="flex-1 rounded border border-ink/15 bg-transparent px-3 py-2 font-mono text-xs dark:border-paper/20"
              />
              <Button type="button" variant="secondary" onClick={() => void copyLink(invite.data.accept_url)}>
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}
    </div>
  );
}
