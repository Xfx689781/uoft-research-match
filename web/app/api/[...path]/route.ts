// Forwards the browser's /api/* calls to the Python API, so visitors only need to reach this one server.
// A route handler (not a next.config rewrite) is used because rewrites drop the visitor's IP, which the
// API needs for its per-visitor rate limits.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";
const FORWARD = ["content-type", "x-forwarded-for", "cf-connecting-ip"];

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = `${API_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const h of FORWARD) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  try {
    const res = await fetch(url, {
      method: req.method,
      headers,
      body: req.method === "GET" ? undefined : await req.text(),
      cache: "no-store",
      signal: AbortSignal.timeout(120_000), // Claude explanations for 10 results can take ~30 s
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
