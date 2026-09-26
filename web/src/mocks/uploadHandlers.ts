/**
 * MSW handlers for uploads and saved column mappings. CSV files are parsed
 * in the browser (comma-separated, no quoting) with the same header aliases
 * the API recognizes — enough for development and component tests.
 */
import { http, HttpResponse } from "msw";
import type { ColumnMapping, ColumnRole, MappingTemplate, MappingTemplateCreate, UploadPreview } from "../api/types";
import { UNAUTHORIZED, authenticate } from "./authHandlers";

const BASE = "*/api/v1";

/** Mirrors the API: lower-case, runs of other characters become one underscore. */
function normalizeHeader(column: string): string {
  return column
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

/** Normalized header -> role, a subset of the API's aliases. */
const ALIASES: Record<string, ColumnRole> = {
  smiles: "smiles",
  canonical_smiles: "smiles",
  inchi: "inchi",
  inchikey: "inchikey",
  compound_id: "source_record_id",
  id: "source_record_id",
  name: "name",
  target: "target",
  mw: "molecular_weight",
  molecular_weight: "molecular_weight",
  activity_value: "activity_value",
  standard_value: "activity_value",
  activity_unit: "activity_unit",
  unit: "activity_unit",
  units: "activity_unit",
  standard_type: "assay_type",
};

/** Uploaded CSV contents, keyed by upload id. */
export const uploadsStore: Record<string, { org_id: string; columns: string[]; rows: Record<string, string>[] }> = {};

/** Saved column mappings, keyed by id. */
export const templatesStore: Record<string, MappingTemplate> = {};

function parseCsv(text: string): { columns: string[]; rows: Record<string, string>[] } {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter((line) => line.trim() !== "");
  const columns = (lines[0] ?? "").split(",").map((c) => c.trim());
  const rows = lines.slice(1).map((line) => {
    const cells = line.split(",");
    return Object.fromEntries(columns.map((column, i) => [column, (cells[i] ?? "").trim()]));
  });
  return { columns, rows };
}

function suggest(orgId: string, columns: string[]): { mapping: ColumnMapping; template: MappingTemplate | null } {
  const matching = Object.values(templatesStore).filter(
    (t) => t.org_id === orgId && Object.keys(t.mapping).every((column) => columns.includes(column)),
  );
  const template = matching.sort((a, b) => Object.keys(b.mapping).length - Object.keys(a.mapping).length)[0];
  if (template) {
    return { mapping: { ...template.mapping }, template };
  }
  const mapping: ColumnMapping = {};
  for (const column of columns) {
    const role = ALIASES[normalizeHeader(column)];
    if (role && !Object.values(mapping).includes(role)) {
      mapping[column] = role;
    }
  }
  return { mapping, template: null };
}

/** Store a CSV upload for `orgId` and build its preview, as `POST /uploads` does. */
export function createUploadPreview(orgId: string, filename: string, text: string): UploadPreview {
  const { columns, rows } = parseCsv(text);
  const id = crypto.randomUUID();
  uploadsStore[id] = { org_id: orgId, columns, rows };
  const { mapping, template } = suggest(orgId, columns);
  return {
    upload: {
      id,
      org_id: orgId,
      filename,
      format: "csv",
      size_bytes: new TextEncoder().encode(text).length,
      sha256: "0".repeat(64),
      created_at: new Date().toISOString(),
    },
    columns,
    rows: rows.slice(0, 20),
    row_count: rows.length,
    suggested_mapping: mapping,
    template,
  };
}

export const uploadHandlers = [
  http.post(`${BASE}/uploads`, async ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const file = (await request.formData()).get("file");
    // Not `instanceof File`: under jsdom, the request's File comes from another realm.
    if (file === null || typeof file === "string") {
      return HttpResponse.json({ detail: "the file is empty" }, { status: 422 });
    }
    if (!/\.(csv|txt)$/i.test(file.name)) {
      return HttpResponse.json(
        { detail: `unsupported file type ${file.name.replace(/^[^.]*/, "") || "(none)"}` },
        { status: 422 },
      );
    }
    return HttpResponse.json(createUploadPreview(org.org_id, file.name, await file.text()), { status: 201 });
  }),

  http.get(`${BASE}/mapping-templates`, ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const templates = Object.values(templatesStore)
      .filter((t) => t.org_id === org.org_id)
      .sort((a, b) => a.name.localeCompare(b.name));
    return HttpResponse.json(templates);
  }),

  http.post(`${BASE}/mapping-templates`, async ({ request }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const body = (await request.json()) as MappingTemplateCreate;
    for (const [id, existing] of Object.entries(templatesStore)) {
      if (existing.org_id === org.org_id && existing.name === body.name) {
        delete templatesStore[id];
      }
    }
    const template: MappingTemplate = {
      id: crypto.randomUUID(),
      org_id: org.org_id,
      name: body.name,
      mapping: body.mapping,
      created_at: new Date().toISOString(),
    };
    templatesStore[template.id] = template;
    return HttpResponse.json(template, { status: 201 });
  }),

  http.delete(`${BASE}/mapping-templates/:id`, ({ request, params }) => {
    const org = authenticate(request);
    if (!org) {
      return HttpResponse.json(UNAUTHORIZED, { status: 401 });
    }
    const template = templatesStore[params.id as string];
    if (template?.org_id !== org.org_id) {
      return HttpResponse.json({ detail: "mapping template not found" }, { status: 404 });
    }
    delete templatesStore[params.id as string];
    return new HttpResponse(null, { status: 204 });
  }),
];
