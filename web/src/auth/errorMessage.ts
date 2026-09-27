/**
 * User-facing message for an error thrown by an auth action. An `ApiError`
 * carries the server's `detail`, which is written for users (unexpected
 * errors come back as a fixed generic body); anything else means the request
 * never got an answer.
 */
import { ApiError } from "../api/client";

export function authErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return err.message;
  }
  return "Could not reach the server. Please try again.";
}
