/** Root application component: providers + router shell. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { SessionProvider } from "./auth/SessionContext";
import { useSession } from "./auth/useSession";
import { AcceptInvite } from "./screens/AcceptInvite";
import { Account } from "./screens/Account";
import { Dashboard } from "./screens/Dashboard";
import { DatasetDetail } from "./screens/DatasetDetail";
import { ExportPanel } from "./screens/ExportPanel";
import { QualityReport } from "./screens/QualityReport";
import { RunTrigger } from "./screens/RunTrigger";
import { Team } from "./screens/Team";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

const NAV_LINK = ({ isActive }: { isActive: boolean }): string =>
  isActive ? "text-accent" : "hover:text-accent";

function AppShell(): React.JSX.Element {
  const { org, signOut } = useSession();

  return (
    <div className="min-h-screen bg-paper text-ink dark:bg-ink dark:text-paper">
      <header className="border-b border-ink/10 dark:border-paper/15">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Link to="/" className="font-display text-xl">
            D&amp;D Labs
          </Link>
          <nav className="flex items-center gap-4 text-sm text-ink/70 dark:text-paper/70">
            {org ? <span>{org.email ? `${org.email} · ${org.org_name}` : org.org_name}</span> : null}
            {org?.role === "admin" ? (
              <NavLink to="/team" className={NAV_LINK}>
                Team
              </NavLink>
            ) : null}
            <NavLink to="/account" className={NAV_LINK}>
              Account
            </NavLink>
            <button type="button" onClick={() => void signOut()} className="hover:text-accent">
              Sign out
            </button>
          </nav>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/new" element={<RunTrigger />} />
          <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
          <Route path="/datasets/:datasetId/quality-report" element={<QualityReport />} />
          <Route path="/datasets/:datasetId/export" element={<ExportPanel />} />
          <Route path="/team" element={<Team />} />
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default function App(): React.JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/invite" element={<AcceptInvite />} />
            <Route
              path="*"
              element={
                <AuthGate>
                  <AppShell />
                </AuthGate>
              }
            />
          </Routes>
        </BrowserRouter>
      </SessionProvider>
    </QueryClientProvider>
  );
}
