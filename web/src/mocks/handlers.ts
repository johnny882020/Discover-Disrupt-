/**
 * MSW request handlers implementing the D&D Labs API contract against the
 * seeded in-memory data in `./data`. Used both by `npm run dev` (so the app
 * is demoable without a real backend) and by component tests.
 */
import { http, HttpResponse } from "msw";
import type {
  Dataset,
  DatasetWithRecords,
  EnrichmentResponse,
  HealthResponse,
  InvitationAccept,
  InvitationCreate,
  InvitationCreated,
  LoginRequest,
  NormalizedRecord,
  OrgContext,
  PasswordChange,
  PipelineRun,
  RunPipelineRequest,
  SessionCreated,
} from "../api/types";
import {
  DATASET_ASPIRIN,
  ENRICHMENT_RESULTS,
  QUALITY_REPORTS,
  SEED_API_KEYS,
  SEED_USERS,
  type SeedUser,
  datasetsStore,
  invitationsStore,
  recordsStore,
  runsStore,
  sessionsStore,
} from "./data";

const BASE = "*/api/v1";

const UNAUTHORIZED = { detail: "missing credentials: send X-API-Key or Authorization: Bearer" };

/** Resolve the caller from `X-API-Key` or `Authorization: Bearer`, as the real API does. */
function authenticate(request: Request): OrgContext | null {
  const key = request.headers.get("X-API-Key");
  if (key) {
    return SEED_API_KEYS[key] ?? null;
  }
  const authorization = request.headers.get("Authorization") ?? "";
  const token = authorization.startsWith("Bearer ") ? authorization.slice("Bearer ".length) : "";
  return sessionsStore[token] ?? null;
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
    expires_at: new Date(Date.now() + 12 * 3600 * 1000).toISOString(),
    user: seed.user,
    org_name: seed.org_name,
  };
}

const MIN_PASSWORD_LENGTH = 12;

const authHandlers = [
  http.post(`${BASE}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as LoginRequest;
    const seed = SEED_USERS[body.email.trim().toLowerCase()];
    if (!seed || seed.password !== body.password) {
      return HttpResponse.json({ detail: "invalid email or password" }, { status: 401 });
    }
    return HttpResponse.json(startSession(seed));
  }),

  http.post(`${BASE}/auth/logout`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    if (org.principal !== "user") {
      return HttpResponse.json({ detail: "this action requires signing in as a user" }, { status: 403 });
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
      return HttpResponse.json({ detail: "this action requires signing in as a user" }, { status: 403 });
    }
    const body = (await request.json()) as PasswordChange;
    if (body.current_password !== seed.password) {
      return HttpResponse.json({ detail: "current password is incorrect" }, { status: 403 });
    }
    if (body.new_password.length < MIN_PASSWORD_LENGTH) {
      return HttpResponse.json(
        { detail: `password must be at least ${MIN_PASSWORD_LENGTH} characters` },
        { status: 422 },
      );
    }
    seed.password = body.new_password;
    return new HttpResponse(null, { status: 204 });
  }),

  http.post(`${BASE}/auth/invitations`, async ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    if (org.role !== "admin") {
      return HttpResponse.json({ detail: "only organization admins can invite members" }, { status: 403 });
    }
    const body = (await request.json()) as InvitationCreate;
    const email = body.email.trim().toLowerCase();
    if (SEED_USERS[email]?.user.org_id === org.org_id) {
      return HttpResponse.json(
        { detail: "this email already belongs to a member of your organization" },
        { status: 409 },
      );
    }
    const token = `ddl_inv_${crypto.randomUUID().replaceAll("-", "")}`;
    const expires_at = new Date(Date.now() + 72 * 3600 * 1000).toISOString();
    invitationsStore[token] = {
      org_id: org.org_id,
      preview: { email, role: body.role, org_name: org.org_name, expires_at },
    };
    const created: InvitationCreated = {
      id: crypto.randomUUID(),
      email,
      role: body.role,
      expires_at,
      token,
      accept_url: `${window.location.origin}/invite#token=${token}`,
    };
    return HttpResponse.json(created, { status: 201 });
  }),

  http.post(`${BASE}/auth/invitations/preview`, async ({ request }) => {
    const { token } = (await request.json()) as { token: string };
    const invitation = invitationsStore[token];
    if (!invitation) {
      return HttpResponse.json({ detail: "invitation is invalid, expired or already used" }, { status: 400 });
    }
    return HttpResponse.json(invitation.preview);
  }),

  http.post(`${BASE}/auth/invitations/accept`, async ({ request }) => {
    const body = (await request.json()) as InvitationAccept;
    const invitation = invitationsStore[body.token];
    if (!invitation) {
      return HttpResponse.json({ detail: "invitation is invalid, expired or already used" }, { status: 400 });
    }
    if (body.password.length < MIN_PASSWORD_LENGTH) {
      return HttpResponse.json(
        { detail: `password must be at least ${MIN_PASSWORD_LENGTH} characters` },
        { status: 422 },
      );
    }
    delete invitationsStore[body.token];
    const { email, role, org_name } = invitation.preview;
    const seed: SeedUser = {
      user: { id: crypto.randomUUID(), org_id: invitation.org_id, email, role, created_at: new Date().toISOString() },
      password: body.password,
      org_name,
    };
    SEED_USERS[email] = seed;
    return HttpResponse.json(startSession(seed), { status: 201 });
  }),
];

export const handlers = [
  ...authHandlers,

  http.get(`${BASE}/health`, () => {
    return HttpResponse.json<HealthResponse>({ status: "ok" });
  }),

  http.get(`${BASE}/auth/whoami`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    return HttpResponse.json(org);
  }),

  http.post(`${BASE}/pipelines/run`, async ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const body = (await request.json()) as RunPipelineRequest;
    const now = new Date().toISOString();
    const runId = `run-${crypto.randomUUID()}`;
    const datasetId = `dataset-${crypto.randomUUID()}`;
    const name = body.dataset_name ?? `${body.source} run`;

    const run: PipelineRun = {
      id: runId,
      org_id: org.org_id,
      spec: {
        source: body.source,
        identifiers: body.identifiers ?? [],
        csv_path: body.csv_path ?? null,
        json_path: body.json_path ?? null,
        chembl_target: body.chembl_target ?? null,
        dataset_name: body.dataset_name ?? null,
      },
      status: "succeeded",
      dataset_id: datasetId,
      error: null,
      created_at: now,
      finished_at: now,
    };
    runsStore.unshift(run);

    const dataset: Dataset = {
      id: datasetId,
      org_id: org.org_id,
      run_id: runId,
      name,
      source: body.source,
      record_count: 3,
      created_at: now,
    };
    datasetsStore.unshift(dataset);
    recordsStore[datasetId] = Array.from({ length: 3 }, (_, i) => ({
      id: `record-${datasetId}-${i}`,
      dataset_id: datasetId,
      record_key: `key-${i}`,
      source: body.source,
      source_record_id: `NEW${i}`,
      name: `New compound ${i}`,
      canonical_smiles: "CC(=O)Oc1ccccc1C(=O)O",
      inchi: null,
      inchikey: null,
      molecular_formula: "C9H8O4",
      molecular_weight: 180 + i,
      target: body.chembl_target ?? null,
      assay_type: null,
      activity_value_nm: null,
      activity_relation: null,
    }));
    QUALITY_REPORTS[datasetId] = {
      run_id: runId,
      dataset_id: datasetId,
      total_records: 3,
      accepted_records: 3,
      rejected_records: 0,
      duplicate_records: 0,
      warning_count: 0,
      error_count: 0,
      issues_by_rule: {},
      issues: [],
      pass_rate: 1,
      created_at: now,
    };
    ENRICHMENT_RESULTS[datasetId] = [];

    return HttpResponse.json(run, { status: 202 });
  }),

  http.get(`${BASE}/pipelines/runs`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    return HttpResponse.json(runsStore.filter((r) => r.org_id === org.org_id));
  }),

  http.get(`${BASE}/pipelines/runs/:id`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const run = runsStore.find((r) => r.id === params.id);
    if (!run) {
      return HttpResponse.json({ detail: "Run not found." }, { status: 404 });
    }
    return HttpResponse.json(run);
  }),

  http.get(`${BASE}/datasets`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    return HttpResponse.json(datasetsStore.filter((d) => d.org_id === org.org_id));
  }),

  http.get(`${BASE}/datasets/:id`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const dataset = datasetsStore.find((d) => d.id === params.id);
    if (!dataset) {
      return HttpResponse.json({ detail: "Dataset not found." }, { status: 404 });
    }
    const body: DatasetWithRecords = {
      dataset,
      records: recordsStore[dataset.id] ?? [],
    };
    return HttpResponse.json(body);
  }),

  http.get(`${BASE}/datasets/:id/records`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const dataset = datasetsStore.find((d) => d.id === params.id);
    if (!dataset) {
      return HttpResponse.json({ detail: "Dataset not found." }, { status: 404 });
    }
    const url = new URL(request.url);
    let records: NormalizedRecord[] = recordsStore[dataset.id] ?? [];

    const mwMin = url.searchParams.get("mw_min");
    const mwMax = url.searchParams.get("mw_max");
    const target = url.searchParams.get("target");
    const source = url.searchParams.get("source");
    const activityMin = url.searchParams.get("activity_min_nm");
    const activityMax = url.searchParams.get("activity_max_nm");
    const limit = Number(url.searchParams.get("limit") ?? "100");
    const offset = Number(url.searchParams.get("offset") ?? "0");

    if (mwMin) records = records.filter((r) => (r.molecular_weight ?? -Infinity) >= Number(mwMin));
    if (mwMax) records = records.filter((r) => (r.molecular_weight ?? Infinity) <= Number(mwMax));
    if (target) records = records.filter((r) => r.target === target);
    if (source) records = records.filter((r) => r.source === source);
    if (activityMin)
      records = records.filter((r) => (r.activity_value_nm ?? -Infinity) >= Number(activityMin));
    if (activityMax)
      records = records.filter((r) => (r.activity_value_nm ?? Infinity) <= Number(activityMax));

    return HttpResponse.json(records.slice(offset, offset + limit));
  }),

  http.get(`${BASE}/datasets/:id/quality-report`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const report = QUALITY_REPORTS[params.id as string];
    if (!report) {
      return HttpResponse.json({ detail: "Quality report not found." }, { status: 404 });
    }
    return HttpResponse.json(report);
  }),

  http.get(`${BASE}/datasets/:id/enrichment`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const results = ENRICHMENT_RESULTS[params.id as string] ?? [];
    const body: EnrichmentResponse = { enrichment_enabled: true, results };
    return HttpResponse.json(body);
  }),

  http.get(`${BASE}/datasets/:id/export`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const url = new URL(request.url);
    const format = url.searchParams.get("format") ?? "csv";
    const records = recordsStore[params.id as string] ?? [];

    if (format === "jsonl") {
      const body = records.map((r) => JSON.stringify(r)).join("\n");
      return new HttpResponse(body, {
        headers: { "Content-Type": "application/x-ndjson" },
      });
    }

    const header = "source_record_id,name,canonical_smiles,molecular_weight,target\n";
    const rows = records
      .map((r) => [r.source_record_id, r.name, r.canonical_smiles, r.molecular_weight, r.target].join(","))
      .join("\n");
    return new HttpResponse(header + rows, {
      headers: { "Content-Type": "text/csv" },
    });
  }),

  http.delete(`${BASE}/orgs/me/data`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    if (org.role !== "admin") {
      return HttpResponse.json(
        { detail: "only organization admins can delete the organization's data" },
        { status: 403 },
      );
    }
    for (let i = datasetsStore.length - 1; i >= 0; i -= 1) {
      if (datasetsStore[i].org_id === org.org_id) {
        datasetsStore.splice(i, 1);
      }
    }
    for (let i = runsStore.length - 1; i >= 0; i -= 1) {
      if (runsStore[i].org_id === org.org_id) {
        runsStore.splice(i, 1);
      }
    }
    return new HttpResponse(null, { status: 204 });
  }),
];

export { DATASET_ASPIRIN };
