"use client";

import { useMemo, useState } from "react";
import type { Paper } from "@/lib/api";

export default function PaperList({ papers }: { papers: Paper[] }) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});

  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    if (!f) return papers;
    return papers.filter((p) =>
      [p.title, p.abstract ?? "", p.venue ?? "", ...p.topics].some((s) => s.toLowerCase().includes(f)),
    );
  }, [papers, filter]);

  return (
    <div>
      <input
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter papers by keyword…"
        className="w-full sm:w-80 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-navy-600"
      />
      <p className="mt-2 text-xs text-slate-500">
        {shown.length} of {papers.length} papers
      </p>
      <ul className="mt-3 divide-y divide-slate-100">
        {shown.map((p) => (
          <li key={p.id} className="py-3">
            <div className="flex gap-3">
              <span className="w-12 shrink-0 text-sm tabular-nums text-slate-400">{p.year ?? "—"}</span>
              <div className="min-w-0 break-anywhere">
                {p.url ? (
                  <a href={p.url} target="_blank" rel="noreferrer" className="font-medium text-navy-700 hover:underline">
                    {p.title}
                  </a>
                ) : (
                  <span className="font-medium">{p.title}</span>
                )}
                {p.venue && <p className="text-sm text-slate-500">{p.venue}</p>}
                {p.abstract ? (
                  <>
                    <button
                      onClick={() => setOpen((o) => ({ ...o, [p.id]: !o[p.id] }))}
                      className="mt-1 text-xs text-slate-500 hover:text-navy-700"
                    >
                      {open[p.id] ? "Hide abstract" : "Show abstract"}
                    </button>
                    {open[p.id] && <p className="mt-1 text-sm leading-relaxed text-slate-700">{p.abstract}</p>}
                  </>
                ) : (
                  <p className="mt-1 text-xs text-slate-400">No abstract in OpenAlex — open the link for the full text.</p>
                )}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
