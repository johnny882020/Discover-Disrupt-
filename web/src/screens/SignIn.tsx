/**
 * Sign-in screen: email and password by default, or an organization API
 * key for programmatic users. New users arrive through an invitation link
 * (`/invite`) instead.
 */
import { useState, type FormEvent } from "react";
import { authErrorMessage } from "../auth/errorMessage";
import { useSession } from "../auth/useSession";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { TextField } from "../design-system/TextField";

type Method = "password" | "api_key";

export function SignIn(): React.JSX.Element {
  const { signIn, signInWithApiKey, notice } = useSession();
  const [method, setMethod] = useState<Method>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      if (method === "password") {
        await signIn(email, password);
      } else {
        await signInWithApiKey(apiKey);
      }
    } catch (err) {
      setError(authErrorMessage(err));
      setPending(false);
    }
  }

  function switchMethod(next: Method): void {
    setMethod(next);
    setError(null);
  }

  const canSubmit = method === "password" ? email.trim() !== "" && password !== "" : apiKey.trim() !== "";

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4 text-ink dark:bg-ink dark:text-paper">
      <Card className="w-full max-w-sm">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <h1 className="font-display text-2xl">D&amp;D Labs</h1>
            <p className="mt-1 text-sm text-ink/60 dark:text-paper/60">
              {method === "password"
                ? "Sign in to your organization."
                : "Sign in with your organization's API key."}
            </p>
          </div>
          {notice ? (
            <p role="status" className="rounded bg-ink/5 px-3 py-2 text-sm dark:bg-paper/10">
              {notice}
            </p>
          ) : null}
          {method === "password" ? (
            <>
              <TextField
                label="Email"
                name="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <TextField
                label="Password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </>
          ) : (
            <TextField
              label="API key"
              name="api-key"
              type="password"
              autoComplete="off"
              placeholder="ddl_live_…"
              className="font-mono"
              required
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          )}
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={pending || !canSubmit}>
            {pending ? "Signing in…" : "Sign in"}
          </Button>
          <button
            type="button"
            onClick={() => switchMethod(method === "password" ? "api_key" : "password")}
            className="text-sm text-ink/60 hover:text-accent dark:text-paper/60"
          >
            {method === "password" ? "Use an API key instead" : "Use email and password instead"}
          </button>
          {method === "password" ? (
            <p className="text-xs text-ink/50 dark:text-paper/50">
              New here? Accounts are created from an invitation sent by your organization&apos;s
              admin.
            </p>
          ) : null}
        </form>
      </Card>
    </div>
  );
}
