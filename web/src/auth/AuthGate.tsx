/**
 * Renders `children` once the user is signed in; otherwise the sign-in
 * screen (or a brief check while a stored credential is re-verified).
 */
import type { ReactNode } from "react";
import { SignIn } from "../screens/SignIn";
import { useSession } from "./useSession";

export function AuthGate({ children }: { children: ReactNode }): React.JSX.Element {
  const { status } = useSession();

  if (status === "signed_in") {
    return <>{children}</>;
  }
  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper text-ink dark:bg-ink dark:text-paper">
        <p className="text-sm text-ink/60 dark:text-paper/60">Checking your session…</p>
      </div>
    );
  }
  return <SignIn />;
}
