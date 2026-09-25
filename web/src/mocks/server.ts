/**
 * MSW Node server, started from `tests/setup.ts` for component tests.
 */
import { setupServer } from "msw/node";
import { handlers } from "./handlers";

export const server = setupServer(...handlers);
