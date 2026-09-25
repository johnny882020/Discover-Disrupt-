import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

async function enableMocking(): Promise<void> {
  if (!(import.meta.env.DEV && import.meta.env.VITE_USE_MOCKS !== "false")) {
    return;
  }
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}

function mount(): void {
  const rootElement = document.getElementById("root");
  if (!rootElement) {
    throw new Error("root element not found");
  }

  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void enableMocking().then(mount);
