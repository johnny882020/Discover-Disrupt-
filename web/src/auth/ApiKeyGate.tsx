/**
 * Gate screen: prompts for an API key, verifies it against `/auth/whoami`,
 * and renders `children` once an org context has been resolved.
 */
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError } from "../api/client";
import { Button } from "../design-system/Button";
import { Card } from "../design-system/Card";
import { useApiKey } from "./useApiKey";

export function ApiKeyGate({ children }: { children: ReactNode }): React.JSX.Element {
  const { apiKey, org, login } = useApiKey();
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [checkingStoredKey, setCheckingStoredKey] = useState(Boolean(apiKey) && !org);

  useEffect(() => {
    if (!apiKey || org) {
      setCheckingStoredKey(false);
      return;
    }
    let cancelled = false;
    setCheckingStoredKey(true);
    login(apiKey)
      .catch(() => {
        if (!cancelled) {
          setError("Your saved key is no longer valid. Please sign in again.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingStoredKey(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // Only re-check when the stored key itself changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey]);

  if (org) {
    return <>{children}</>;
  }

  if (checkingStoredKey) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-ink dark:bg-ink dark:text-paper">
        <p className="text-sm text-ink/60 dark:text-paper/60">Verifying saved key…</p>
      </div>
    );
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(input);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.status === 401 ? "That API key was not recognized." : err.message);
      } else {
        setError("Could not reach the server. Please try again.");
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4 text-ink dark:bg-ink dark:text-paper">
      <Card className="w-full max-w-sm">
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <h1 className="font-display text-2xl">D&amp;D Labs</h1>
            <p className="mt-1 text-sm text-ink/60 dark:text-paper/60">
              Enter your organization&apos;s API key to continue.
            </p>
          </div>
          <label className="flex flex-col gap-1.5 text-sm" htmlFor="api-key-input">
            <span className="font-medium">API key</span>
            <input
              id="api-key-input"
              name="api-key"
              type="password"
              autoComplete="off"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="dnd_live_..."
              className="rounded border border-ink/15 bg-transparent px-3 py-2 font-mono text-sm outline-none focus:border-accent dark:border-paper/20"
            />
          </label>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={pending || input.trim().length === 0}>
            {pending ? "Verifying…" : "Continue"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
