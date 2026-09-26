/** User-facing message for an error thrown by an auth action. */
import { ApiError } from "../api/client";

export function authErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message;
  }
  return "Could not reach the server. Please try again.";
}
