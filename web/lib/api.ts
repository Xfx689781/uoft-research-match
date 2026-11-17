// In the browser, call this site's own /api (proxied to the Python API by next.config.ts rewrites).
// On the server (professor pages, footer metadata), call the Python API directly.
export const API_URL =
  typeof window === "undefined" ? (process.env.API_URL ?? "http://127.0.0.1:8000") : "";

// Server-only (not NEXT_PUBLIC_, so never in browser bundles): proves to the deployed API that the call
// comes from this website.
export function serverApiHeaders(): Record<string, string> {
  const secret = process.env.PROXY_SECRET;
  return secret ? { "x-proxy-secret": secret } : {};
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export type Appointment = {
  department_id: string;
  department: string;
  title: string;
  faculty_id: string;
  profile_url: string | null;
  appointment_type?: string;
  home_unit?: string | null;
};

export type PaperHit = {
  title: string;
  year: number | null;
  venue: string | null;
  url: string | null;
  similarity: number;
};

export type SearchResult = {
  id: string;
  person_key: string;
  name: string;
  title: string;
  appointments: Appointment[];
  score: number;
  match: "strong" | "good" | "partial";
  why: string;
  why_source: "llm" | "cache" | "template";
  top_papers: PaperHit[];
  research_areas: string[];
  email: string | null;
  profile_url: string | null;
  website: string | null;
  source_url: string;
  is_emeritus: boolean;
  accepting_students: boolean | null;
  notes: string[];
  has_publications: boolean;
};

export type SearchParams = {
  query: string;
  departments?: string[];
  include_emeriti?: boolean;
  k?: number;
};

export type Paper = {
  id: string;
  title: string;
  abstract: string | null;
  year: number | null;
  pub_date: string | null;
  venue: string | null;
  type: string | null;
  url: string | null;
  doi: string | null;
  topics: string[];
};

export type Topic = { name: string; subfield: string; field: string; count: number };

export type Professor = {
  id: string;
  name: string;
  title: string;
  appointments: Appointment[];
  email: string | null;
  website: string | null;
  profile_url: string | null;
  source_url: string;
  research_areas: string[];
  topics: Topic[];
  is_emeritus: boolean;
  accepting_students: boolean | null;
  notes: string[];
  openalex_id: string | null;
  papers: Paper[];
};

export type Meta = {
  departments: { id: string; name: string; directory_url: string; last_scraped_at: string | null; faculty: number }[];
  data_last_updated: string | null;
  explanations: "claude" | "template";
  searchable_professors: number;
};

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new ApiError(res.status, `${path} failed (${res.status})`);
  return res.json();
}

export const search = (p: SearchParams, signal?: AbortSignal) =>
  post<{ query: string; results: SearchResult[] }>("/api/search", p, signal);

export const explain = (p: SearchParams, signal?: AbortSignal) =>
  post<{ query: string; explanations: Record<string, { why: string; source: string }> }>("/api/explain", p, signal);

export async function getProfessor(id: string): Promise<Professor | null> {
  const res = await fetch(`${API_URL}/api/professors/${encodeURIComponent(id)}`, {
    cache: "no-store",
    headers: serverApiHeaders(),
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`professor fetch failed (${res.status})`);
  return res.json();
}

// Public address of the site, for the sitemap and search-engine metadata. SITE_URL wins (set it when a
// custom domain is added); on Vercel, VERCEL_PROJECT_PRODUCTION_URL is provided automatically.
export const SITE_URL = (
  process.env.SITE_URL ??
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : "http://localhost:3000")
).replace(/\/$/, "");

export async function listProfessors(): Promise<{ id: string; name: string }[]> {
  const res = await fetch(`${API_URL}/api/professors`, {
    next: { revalidate: 86400 },
    headers: serverApiHeaders(),
    signal: AbortSignal.timeout(90_000),
  });
  if (!res.ok) throw new Error(`professor list failed (${res.status})`);
  return (await res.json()).professors;
}

export async function getMeta(): Promise<Meta | null> {
  try {
    const res = await fetch(`${API_URL}/api/meta`, {
      next: { revalidate: 300 },
      headers: serverApiHeaders(),
      signal: AbortSignal.timeout(8000), // a sleeping free-tier API must not hold up every page
    });
    return res.ok ? res.json() : null;
  } catch {
    return null;
  }
}

export const DEPARTMENTS = [
  { id: "cs", label: "Computer Science" },
  { id: "math", label: "Mathematics" },
  { id: "stats", label: "Statistics" },
] as const;

export const shortDept = (id: string) =>
  ({ cs: "CS", math: "Math", stats: "Stats" } as Record<string, string>)[id] ?? id;

export const professorHref = (id: string) => `/professors/${encodeURIComponent(id)}`;

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  return new Date(iso).toLocaleDateString("en-CA", { year: "numeric", month: "long", day: "numeric" });
}
