/**
 * MSW browser worker, started from `main.tsx` in development builds only.
 */
import { setupWorker } from "msw/browser";
import { handlers } from "./handlers";

export const worker = setupWorker(...handlers);
