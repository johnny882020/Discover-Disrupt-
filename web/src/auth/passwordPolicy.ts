/**
 * Client-side mirror of the server's password length rule, for immediate
 * feedback. The server remains the authority (it also screens common
 * passwords and the account's email), and its message is shown on failure.
 */
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 128;

export const PASSWORD_HINT = `At least ${MIN_PASSWORD_LENGTH} characters. A few unrelated words make a strong, memorable password.`;

/** Returns why a new password is unacceptable, or `null` if it may be submitted. */
export function newPasswordProblem(password: string, confirmation: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `Password must be at most ${MAX_PASSWORD_LENGTH} characters.`;
  }
  if (password !== confirmation) {
    return "Passwords do not match.";
  }
  return null;
}
