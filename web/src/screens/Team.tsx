/**
 * Team screen (admins): invite colleagues, manage members' roles, issue
 * password-reset links, remove members and revoke pending invitations.
 * Invitation and reset links are shown once, to be sent to the person.
 */
import { useState, type FormEvent } from "react";
import type { Role, User } from "../api/types";
import { authErrorMessage } from "../auth/errorMessage";
import { useSession } from "../auth/useSession";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { Table, type TableColumn } from "../design-system/Table";
import { TextField } from "../design-system/TextField";
import {
  useChangeRole,
  useInvite,
  useIssuePasswordReset,
  useMembers,
  usePendingInvitations,
  useRemoveMember,
  useRevokeInvitation,
} from "../hooks/useTeam";

/** A single-use link to hand to someone, shown once. */
interface OneTimeLink {
  heading: string;
  email: string;
  url: string;
  expiresAt: string;
}

const SELECT_CLASS =
  "rounded border border-ink/15 bg-transparent px-2 py-1 text-sm dark:border-paper/20";

function formatDate(value: string): string {
  return new Date(value).toLocaleString();
}

function LinkCard({ link }: { link: OneTimeLink }): React.JSX.Element {
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(link.url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-col gap-3">
        <h2 className="font-display text-xl">{link.heading}</h2>
        <p className="text-sm text-ink/70 dark:text-paper/70">
          Send this link to {link.email}. It works once, expires on {formatDate(link.expiresAt)}, and
          is not shown again.
        </p>
        <div className="flex gap-2">
          <input
            aria-label="One-time link"
            readOnly
            value={link.url}
            onFocus={(e) => e.currentTarget.select()}
            className="flex-1 rounded border border-ink/15 bg-transparent px-3 py-2 font-mono text-xs dark:border-paper/20"
          />
          <Button type="button" variant="secondary" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </div>
    </Card>
  );
}

function InviteForm({ onCreated }: { onCreated: (link: OneTimeLink) => void }): React.JSX.Element {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const invite = useInvite();

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    invite.mutate(
      { email: email.trim(), role },
      {
        onSuccess: (created) => {
          setEmail("");
          onCreated({
            heading: `Invitation for ${created.email}`,
            email: created.email,
            url: created.accept_url,
            expiresAt: created.expires_at,
          });
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 sm:max-w-md">
      <h2 className="font-display text-xl">Invite a colleague</h2>
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
          <option value="admin">Admin — can also manage the team</option>
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
  );
}

function MembersTable({
  currentUserId,
  onReset,
}: {
  currentUserId: string | null;
  onReset: (link: OneTimeLink) => void;
}): React.JSX.Element {
  const members = useMembers();
  const changeRole = useChangeRole();
  const removeMember = useRemoveMember();
  const issueReset = useIssuePasswordReset();
  const [confirmingRemoval, setConfirmingRemoval] = useState<string | null>(null);
  const error = changeRole.error ?? removeMember.error ?? issueReset.error;

  function reset(member: User): void {
    issueReset.mutate(member.id, {
      onSuccess: (created) =>
        onReset({
          heading: `Password-reset link for ${created.email}`,
          email: created.email,
          url: created.reset_url,
          expiresAt: created.expires_at,
        }),
    });
  }

  const columns: TableColumn<User>[] = [
    {
      key: "email",
      header: "Email",
      cell: (member) => (member.id === currentUserId ? `${member.email} (you)` : member.email),
    },
    {
      key: "role",
      header: "Role",
      cell: (member) => (
        <select
          aria-label={`Role for ${member.email}`}
          value={member.role}
          disabled={changeRole.isPending}
          onChange={(e) => changeRole.mutate({ userId: member.id, role: e.target.value as Role })}
          className={SELECT_CLASS}
        >
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </select>
      ),
    },
    { key: "joined", header: "Joined", cell: (member) => new Date(member.created_at).toLocaleDateString() },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (member) =>
        confirmingRemoval === member.id ? (
          <span className="inline-flex gap-2">
            <Button
              type="button"
              variant="danger"
              onClick={() => removeMember.mutate(member.id, { onSettled: () => setConfirmingRemoval(null) })}
            >
              Confirm removal
            </Button>
            <Button type="button" variant="ghost" onClick={() => setConfirmingRemoval(null)}>
              Cancel
            </Button>
          </span>
        ) : (
          <span className="inline-flex gap-2">
            <Button type="button" variant="ghost" disabled={issueReset.isPending} onClick={() => reset(member)}>
              Reset password
            </Button>
            {member.id === currentUserId ? null : (
              <Button type="button" variant="ghost" onClick={() => setConfirmingRemoval(member.id)}>
                Remove
              </Button>
            )}
          </span>
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-display text-xl">Members</h2>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {authErrorMessage(error)}
        </p>
      ) : null}
      {members.isError ? (
        <p role="alert" className="text-sm text-danger">
          {authErrorMessage(members.error)}
        </p>
      ) : members.data ? (
        <Table columns={columns} rows={members.data} getRowKey={(member) => member.id} />
      ) : (
        <p className="text-sm text-ink/60 dark:text-paper/60">Loading members…</p>
      )}
    </div>
  );
}

function PendingInvitations(): React.JSX.Element {
  const invitations = usePendingInvitations();
  const revoke = useRevokeInvitation();

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-display text-xl">Pending invitations</h2>
      {revoke.isError ? (
        <p role="alert" className="text-sm text-danger">
          {authErrorMessage(revoke.error)}
        </p>
      ) : null}
      {invitations.data && invitations.data.length === 0 ? (
        <p className="text-sm text-ink/60 dark:text-paper/60">No pending invitations.</p>
      ) : null}
      {invitations.data && invitations.data.length > 0 ? (
        <Table
          columns={[
            { key: "email", header: "Email", cell: (i) => i.email },
            { key: "role", header: "Role", cell: (i) => <span className="capitalize">{i.role}</span> },
            { key: "expires", header: "Expires", cell: (i) => formatDate(i.expires_at) },
            {
              key: "revoke",
              header: "",
              align: "right",
              cell: (i) => (
                <Button type="button" variant="ghost" disabled={revoke.isPending} onClick={() => revoke.mutate(i.id)}>
                  Revoke
                </Button>
              ),
            },
          ]}
          rows={invitations.data}
          getRowKey={(i) => i.id}
        />
      ) : null}
    </div>
  );
}

export function Team(): React.JSX.Element {
  const { org } = useSession();
  const [link, setLink] = useState<OneTimeLink | null>(null);

  if (org?.role !== "admin") {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="font-display text-3xl">Team</h1>
        <Card>
          <p className="text-sm">Only your organization&apos;s admins can manage the team.</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="font-display text-3xl">Team</h1>
        <p className="mt-1 text-sm text-ink/60 dark:text-paper/60">
          Manage who can access {org.org_name}. People choose their own passwords from the links you
          send them.
        </p>
      </div>
      {link ? <LinkCard key={link.url} link={link} /> : null}
      <Card>
        <InviteForm onCreated={setLink} />
      </Card>
      <Card>
        <MembersTable currentUserId={org.user_id} onReset={setLink} />
      </Card>
      <Card>
        <PendingInvitations />
      </Card>
    </div>
  );
}
