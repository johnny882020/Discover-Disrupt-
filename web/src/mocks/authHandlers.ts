/**
 * MSW handlers for the auth API — sign-in, sessions, invitations, members
 * and password resets — mirroring the real endpoints' contracts, statuses
 * and messages closely enough for development and component tests.
 */
import { http, HttpResponse } from "msw";
import type {
  Invitation,
  InvitationAccept,
  InvitationCreate,
  InvitationCreated,
  LoginRequest,
  MemberUpdate,
  OrgContext,
  PasswordChange,
  PasswordResetCreated,
  PasswordResetPreview,
  Role,
  SessionCreated,
} from "../api/types";
import { SEED_API_KEYS, SEED_USERS, invitationsStore, sessionsStore, type SeedUser } from "./data";

const BASE = "*/api/v1";
const MIN_PASSWORD_LENGTH = 12;
const HOUR_MS = 3600 * 1000;
const INVALID_TOKEN = { detail: "invitation is invalid, expired or already used" };

export const UNAUTHORIZED = { detail: "missing credentials: send X-API-Key or Authorization: Bearer" };

/** Resolve the caller from `X-API-Key` or `Authorization: Bearer`, as the real API does. */
export function authenticate(request: Request): OrgContext | null {
  const key = request.headers.get("X-API-Key");
  if (key) {
    return SEED_API_KEYS[key] ?? null;
  }
  const authorization = request.headers.get("Authorization") ?? "";
  const token = authorization.startsWith("Bearer ") ? authorization.slice("Bearer ".length) : "";
  return sessionsStore[token] ?? null;
}

function error(detail: string, status: number): Response {
  return HttpResponse.json({ detail }, { status });
}

/** The caller, or an error response: 401 if unauthenticated, 403 if not an admin. */
function requireAdmin(request: Request): OrgContext | Response {
  const org = authenticate(request);
  if (!org) {
    return HttpResponse.json(UNAUTHORIZED, { status: 401 });
  }
  if (org.role !== "admin") {
    return error("only organization admins can manage members", 403);
  }
  return org;
}

function startSession(seed: SeedUser): SessionCreated {
  const token = `ddl_sess_${crypto.randomUUID().replaceAll("-", "")}`;
  sessionsStore[token] = {
    org_id: seed.user.org_id,
    org_name: seed.org_name,
    principal: "user",
    role: seed.user.role,
    api_key_id: null,
    user_id: seed.user.id,
    session_id: crypto.randomUUID(),
    email: seed.user.email,
  };
  return {
    token,
    token_type: "bearer",
    expires_at: new Date(Date.now() + 12 * HOUR_MS).toISOString(),
    user: seed.user,
    org_name: seed.org_name,
  };
}

function endSessionsOf(userId: string): void {
  for (const [token, ctx] of Object.entries(sessionsStore)) {
    if (ctx.user_id === userId) {
      delete sessionsStore[token];
    }
  }
}

function membersOf(orgId: string): SeedUser[] {
  return Object.values(SEED_USERS).filter((seed) => seed.user.org_id === orgId);
}

function memberById(orgId: string, userId: string): SeedUser | undefined {
  return membersOf(orgId).find((seed) => seed.user.id === userId);
}

function hasAnotherAdmin(orgId: string, userId: string): boolean {
  return membersOf(orgId).some((seed) => seed.user.role === "admin" && seed.user.id !== userId);
}

function storeToken(
  org: Pick<OrgContext, "org_id" | "org_name">,
  email: string,
  role: Role,
  purpose: Invitation["purpose"],
  ttlHours: number,
): { token: string; invitation: Invitation } {
  const token = `ddl_inv_${crypto.randomUUID().replaceAll("-", "")}`;
  const invitation: Invitation = {
    id: crypto.randomUUID(),
    org_id: org.org_id,
    email,
    role,
    purpose,
    created_by: null,
    created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + ttlHours * HOUR_MS).toISOString(),
    accepted_at: null,
    revoked_at: null,
  };
  invitationsStore[token] = { invitation, org_name: org.org_name };
  return { token, invitation };
}

function redeemable(token: string, purpose: Invitation["purpose"]) {
  const stored = invitationsStore[token];
  return stored && stored.invitation.purpose === purpose ? stored : undefined;
}

function passwordTooShort(password: string): Response | null {
  return password.length < MIN_PASSWORD_LENGTH
    ? error(`password must be at least ${MIN_PASSWORD_LENGTH} characters`, 422)
    : null;
}

export const authHandlers = [
  http.post(`${BASE}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as LoginRequest;
    const seed = SEED_USERS[body.email.trim().toLowerCase()];
    if (!seed || seed.password !== body.password) {
      return error("invalid email or password", 401);
    }
    return HttpResponse.json(startSession(seed));
  }),

  http.post(`${BASE}/auth/logout`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    if (org.principal !== "user") {
      return error("this action requires signing in as a user", 403);
    }
    const token = (request.headers.get("Authorization") ?? "").slice("Bearer ".length);
    delete sessionsStore[token];
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${BASE}/auth/password`, async ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const seed = org.email ? SEED_USERS[org.email] : undefined;
    if (org.principal !== "user" || !seed) {
      return error("this action requires signing in as a user", 403);
    }
    const body = (await request.json()) as PasswordChange;
    if (body.current_password !== seed.password) {
      return error("current password is incorrect", 403);
    }
    const tooShort = passwordTooShort(body.new_password);
    if (tooShort) {
      return tooShort;
    }
    seed.password = body.new_password;
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`${BASE}/auth/invitations`, ({ request }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    const pending = Object.values(invitationsStore)
      .map((stored) => stored.invitation)
      .filter((i) => i.org_id === org.org_id && i.purpose === "join")
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json(pending);
  }),

  http.post(`${BASE}/auth/invitations`, async ({ request }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    const body = (await request.json()) as InvitationCreate;
    const email = body.email.trim().toLowerCase();
    if (SEED_USERS[email]?.user.org_id === org.org_id) {
      return error("this email already belongs to a member of your organization", 409);
    }
    const { token, invitation } = storeToken(org, email, body.role, "join", 72);
    const created: InvitationCreated = {
      id: invitation.id,
      email,
      role: body.role,
      expires_at: invitation.expires_at,
      token,
      accept_url: `${window.location.origin}/invite#token=${token}`,
    };
    return HttpResponse.json(created, { status: 201 });
  }),

  http.delete(`${BASE}/auth/invitations/:id`, ({ request, params }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    const entry = Object.entries(invitationsStore).find(
      ([, stored]) => stored.invitation.id === params.id && stored.invitation.org_id === org.org_id,
    );
    if (!entry) {
      return error("pending invitation not found", 404);
    }
    delete invitationsStore[entry[0]];
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${BASE}/auth/invitations/preview`, async ({ request }) => {
    const { token } = (await request.json()) as { token: string };
    const stored = redeemable(token, "join");
    if (!stored) {
      return HttpResponse.json(INVALID_TOKEN, { status: 400 });
    }
    const { email, role, expires_at } = stored.invitation;
    return HttpResponse.json({ email, role, org_name: stored.org_name, expires_at });
  }),

  http.post(`${BASE}/auth/invitations/accept`, async ({ request }) => {
    const body = (await request.json()) as InvitationAccept;
    const stored = redeemable(body.token, "join");
    if (!stored) {
      return HttpResponse.json(INVALID_TOKEN, { status: 400 });
    }
    const tooShort = passwordTooShort(body.password);
    if (tooShort) {
      return tooShort;
    }
    delete invitationsStore[body.token];
    const { email, role, org_id } = stored.invitation;
    const seed: SeedUser = {
      user: { id: crypto.randomUUID(), org_id, email, role, created_at: new Date().toISOString() },
      password: body.password,
      org_name: stored.org_name,
    };
    SEED_USERS[email] = seed;
    return HttpResponse.json(startSession(seed), { status: 201 });
  }),

  http.get(`${BASE}/auth/members`, ({ request }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    const members = membersOf(org.org_id)
      .map((seed) => seed.user)
      .sort((a, b) => a.created_at.localeCompare(b.created_at));
    return HttpResponse.json(members);
  }),

  http.patch(`${BASE}/auth/members/:id`, async ({ request, params }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    const seed = memberById(org.org_id, params.id as string);
    if (!seed) {
      return error("user not found", 404);
    }
    const body = (await request.json()) as MemberUpdate;
    if (seed.user.role === "admin" && body.role !== "admin" && !hasAnotherAdmin(org.org_id, seed.user.id)) {
      return error("an organization must keep at least one admin", 409);
    }
    seed.user = { ...seed.user, role: body.role };
    return HttpResponse.json(seed.user);
  }),

  http.delete(`${BASE}/auth/members/:id`, ({ request, params }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    if (params.id === org.user_id) {
      return error("you cannot remove yourself; ask another admin", 403);
    }
    const seed = memberById(org.org_id, params.id as string);
    if (!seed) {
      return error("user not found", 404);
    }
    if (seed.user.role === "admin" && !hasAnotherAdmin(org.org_id, seed.user.id)) {
      return error("an organization must keep at least one admin", 409);
    }
    delete SEED_USERS[seed.user.email];
    endSessionsOf(seed.user.id);
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${BASE}/auth/members/:id/password-reset`, ({ request, params }) => {
    const org = requireAdmin(request);
    if (org instanceof Response) {
      return org;
    }
    const seed = memberById(org.org_id, params.id as string);
    if (!seed) {
      return error("user not found", 404);
    }
    const { token, invitation } = storeToken(org, seed.user.email, seed.user.role, "password_reset", 24);
    const created: PasswordResetCreated = {
      email: seed.user.email,
      expires_at: invitation.expires_at,
      token,
      reset_url: `${window.location.origin}/reset#token=${token}`,
    };
    return HttpResponse.json(created, { status: 201 });
  }),

  http.post(`${BASE}/auth/password-reset/preview`, async ({ request }) => {
    const { token } = (await request.json()) as { token: string };
    const stored = redeemable(token, "password_reset");
    if (!stored) {
      return HttpResponse.json(INVALID_TOKEN, { status: 400 });
    }
    const preview: PasswordResetPreview = {
      email: stored.invitation.email,
      org_name: stored.org_name,
      expires_at: stored.invitation.expires_at,
    };
    return HttpResponse.json(preview);
  }),

  http.post(`${BASE}/auth/password-reset/accept`, async ({ request }) => {
    const body = (await request.json()) as InvitationAccept;
    const stored = redeemable(body.token, "password_reset");
    const seed = stored ? SEED_USERS[stored.invitation.email] : undefined;
    if (!stored || !seed) {
      return HttpResponse.json(INVALID_TOKEN, { status: 400 });
    }
    const tooShort = passwordTooShort(body.password);
    if (tooShort) {
      return tooShort;
    }
    delete invitationsStore[body.token];
    seed.password = body.password;
    endSessionsOf(seed.user.id);
    return HttpResponse.json(startSession(seed));
  }),
];
