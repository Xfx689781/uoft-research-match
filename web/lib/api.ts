export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  if (!res.ok) throw new Error(`${path} failed (${res.status})`);
  return res.json();
}

export const search = (p: SearchParams, signal?: AbortSignal) =>
  post<{ query: string; results: SearchResult[] }>("/api/search", p, signal);

export const explain = (p: SearchParams, signal?: AbortSignal) =>
  post<{ query: string; explanations: Record<string, { why: string; source: string }> }>("/api/explain", p, signal);

export async function getProfessor(id: string): Promise<Professor | null> {
  const res = await fetch(`${API_URL}/api/professors/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`professor fetch failed (${res.status})`);
  return res.json();
}

export async function getMeta(): Promise<Meta | null> {
  try {
    const res = await fetch(`${API_URL}/api/meta`, { next: { revalidate: 300 } });
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
