/** Root application component: providers + router shell. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, Navigate, Route, BrowserRouter, Routes } from "react-router-dom";
import { ApiKeyGate } from "./auth/ApiKeyGate";
import { ApiKeyProvider, useApiKey } from "./auth/ApiKeyContext";
import { Dashboard } from "./screens/Dashboard";
import { DatasetDetail } from "./screens/DatasetDetail";
import { ExportPanel } from "./screens/ExportPanel";
import { QualityReport } from "./screens/QualityReport";
import { RunTrigger } from "./screens/RunTrigger";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

function AppShell(): React.JSX.Element {
  const { org, logout } = useApiKey();

  return (
    <div className="min-h-screen bg-paper text-ink dark:bg-ink dark:text-paper">
      <header className="border-b border-ink/10 dark:border-paper/15">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <Link to="/" className="font-display text-xl">
            D&amp;D Labs
          </Link>
          <div className="flex items-center gap-4 text-sm text-ink/70 dark:text-paper/70">
            {org ? <span>{org.org_name}</span> : null}
            <button type="button" onClick={logout} className="hover:text-accent">
              Sign out
            </button>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/runs/new" element={<RunTrigger />} />
          <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
          <Route path="/datasets/:datasetId/quality-report" element={<QualityReport />} />
          <Route path="/datasets/:datasetId/export" element={<ExportPanel />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </div>
    </div>
  );
}

export default function App(): React.JSX.Element {
  return (
    <QueryClientProvider client={queryClient}>
      <ApiKeyProvider>
        <BrowserRouter>
          <ApiKeyGate>
            <AppShell />
          </ApiKeyGate>
        </BrowserRouter>
      </ApiKeyProvider>
    </QueryClientProvider>
  );
}
