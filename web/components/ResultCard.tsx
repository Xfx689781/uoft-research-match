import Link from "next/link";
import { professorHref, shortDept, type SearchResult } from "@/lib/api";

const MATCH_STYLE: Record<SearchResult["match"], string> = {
  strong: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  good: "bg-sky-50 text-sky-700 ring-sky-200",
  partial: "bg-slate-50 text-slate-600 ring-slate-200",
};

export default function ResultCard({ r, rank, explaining }: { r: SearchResult; rank: number; explaining: boolean }) {
  const llm = r.why_source === "llm" || r.why_source === "cache";
  return (
    <article className="rounded-xl bg-white p-4 sm:p-5 shadow-sm ring-1 ring-slate-200">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-navy-800">
            <span className="text-slate-400 font-normal mr-1">{rank}.</span>
            <Link href={professorHref(r.id)} className="hover:underline">
              {r.name}
            </Link>
          </h3>
          <p className="text-sm text-slate-600">
            {r.title} · {r.appointments.map((a) => shortDept(a.department_id)).join(" + ")}
          </p>
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ${MATCH_STYLE[r.match]}`}>
          {r.match} match
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {r.is_emeritus && <Badge tone="amber">Emeritus</Badge>}
        {r.accepting_students === false && <Badge tone="rose">Not accepting new grad students (per dept. page)</Badge>}
        {!r.has_publications && <Badge tone="slate">No publication data — matched on dept. page only</Badge>}
      </div>

      <p className="mt-3 text-sm leading-relaxed text-slate-800">
        <span className="font-medium text-navy-700">Why this match: </span>
        {r.why}
        {!llm && explaining && <span className="ml-1 text-xs text-slate-400 animate-pulse">(writing a better explanation…)</span>}
      </p>

      {r.top_papers.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Papers that drove this match</p>
          <ul className="mt-1 space-y-1">
            {r.top_papers.map((p) => (
              <li key={p.title} className="text-sm break-anywhere">
                {p.url ? (
                  <a href={p.url} target="_blank" rel="noreferrer" className="text-navy-600 hover:underline">
                    {p.title}
                  </a>
                ) : (
                  p.title
                )}
                <span className="text-slate-500">
                  {" "}
                  ({[p.venue, p.year].filter(Boolean).join(", ")})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <Link href={professorHref(r.id)} className="font-medium text-navy-700 hover:underline">
          All papers & profile →
        </Link>
        {r.email && (
          <a href={`mailto:${r.email}`} className="text-slate-600 hover:underline break-anywhere">
            {r.email}
          </a>
        )}
        <a href={r.profile_url ?? r.website ?? r.source_url} target="_blank" rel="noreferrer" className="text-slate-600 hover:underline">
          Official page ↗
        </a>
      </div>
    </article>
  );
}

function Badge({ tone, children }: { tone: "amber" | "rose" | "slate"; children: React.ReactNode }) {
  const t = {
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    rose: "bg-rose-50 text-rose-700 ring-rose-200",
    slate: "bg-slate-50 text-slate-600 ring-slate-200",
  }[tone];
  return <span className={`rounded-md px-2 py-0.5 text-xs ring-1 ${t}`}>{children}</span>;
}
