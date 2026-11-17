// Forwards the browser's /api/* calls to the Python API, so visitors only ever talk to this website.
// A route handler (not a next.config rewrite) is used because rewrites drop the visitor's IP, which the
// API needs for its per-visitor rate limits.
import type { NextRequest } from "next/server";
import { serverApiHeaders } from "@/lib/api";

export const dynamic = "force-dynamic";
export const maxDuration = 120; // Vercel: free-tier API wake-up (~1 min) plus Claude explanations (~30 s)

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

function visitorIp(req: NextRequest): string | null {
  // On Vercel, x-forwarded-for is set by Vercel's edge to the real client IP (client values are replaced).
  return req.headers.get("cf-connecting-ip") ?? req.headers.get("x-forwarded-for")?.split(",")[0].trim() ?? null;
}

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = `${API_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers(serverApiHeaders());
  const ct = req.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  const ip = visitorIp(req);
  if (ip) {
    headers.set("x-visitor-ip", ip); // used by the deployed API (PROXY_SECRET set)
    headers.set("x-forwarded-for", req.headers.get("x-forwarded-for") ?? ip); // used locally
  }
  try {
    const res = await fetch(url, {
      method: req.method,
      headers,
      body: req.method === "GET" ? undefined : await req.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(110_000),
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "API unavailable" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST };
