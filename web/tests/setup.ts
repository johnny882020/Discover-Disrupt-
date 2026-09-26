import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "../src/mocks/server";

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  server.resetHandlers();
  // Absent in files that opt into the Node environment (`@vitest-environment node`).
  globalThis.sessionStorage?.clear();
  globalThis.localStorage?.clear();
});

afterAll(() => {
  server.close();
});
