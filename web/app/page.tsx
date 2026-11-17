"use client";

import { useRef, useState } from "react";
import ResultCard from "@/components/ResultCard";
import { DEPARTMENTS, explain, search, type SearchParams, type SearchResult } from "@/lib/api";

const EXAMPLES = [
  "Bayesian inference and probabilistic machine learning",
  "I took STA302 and CSC311 and want to work on fairness of ML models used in hospitals",
  "algebraic topology, especially homotopy theory",
  "reinforcement learning for robot manipulation",
  "number theory and cryptography",
];

export default function Home() {
  const [query, setQuery] = useState("");
  const [depts, setDepts] = useState<string[]>([]);
  const [includeEmeriti, setIncludeEmeriti] = useState(true);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function run(q: string) {
    const text = q.trim();
    if (text.length < 2) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const params: SearchParams = {
      query: text,
      departments: depts.length ? depts : undefined,
      include_emeriti: includeEmeriti,
      k: 10,
    };
    setLoading(true);
    setError(null);
    try {
      const { results } = await search(params, ctrl.signal);
      setResults(results);
      setLoading(false);
      if (results.some((r) => r.why_source === "template")) {
        setExplaining(true);
        try {
          const { explanations } = await explain(params, ctrl.signal);
          setResults((cur) =>
            cur?.map((r) =>
              explanations[r.person_key] ? { ...r, why: explanations[r.person_key].why, why_source: explanations[r.person_key].source as SearchResult["why_source"] } : r,
            ) ?? cur,
          );
        } catch {
          /* keep template sentences */
        } finally {
          if (!ctrl.signal.aborted) setExplaining(false);
        }
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setError("Search failed. Is the API running? (python serve_api.py)");
        setLoading(false);
      }
      console.error(e);
    }
  }

  const toggleDept = (id: string) => setDepts((d) => (d.includes(id) ? d.filter((x) => x !== id) : [...d, id]));

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:py-12">
      <section className="max-w-3xl">
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-navy-800">
          Find a research supervisor at UofT
        </h1>
        <p className="mt-3 text-slate-600">
          Describe what you want to work on — a few keywords, or a paragraph about your background and interests. We
          match it against professors&apos; recent papers, not just their one-line bios.
        </p>
      </section>

      <form
        className="mt-6 max-w-3xl"
        onSubmit={(e) => {
          e.preventDefault();
          run(query);
        }}
      >
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(query);
          }}
          rows={3}
          maxLength={4000}
          placeholder="e.g. I'm interested in causal inference with electronic health records, and I've taken STA302…"
          className="w-full rounded-xl border border-slate-300 bg-white p-4 text-base shadow-sm outline-none focus:border-navy-600 focus:ring-2 focus:ring-navy-100"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {DEPARTMENTS.map((d) => {
            const on = depts.includes(d.id);
            return (
              <button
                key={d.id}
                type="button"
                onClick={() => toggleDept(d.id)}
                aria-pressed={on}
                className={`rounded-full px-3 py-1.5 text-sm ring-1 transition ${
                  on ? "bg-navy-700 text-white ring-navy-700" : "bg-white text-slate-700 ring-slate-300 hover:ring-navy-600"
                }`}
              >
                {d.label}
              </button>
            );
          })}
          <label className="ml-1 flex items-center gap-1.5 text-sm text-slate-600">
            <input type="checkbox" checked={includeEmeriti} onChange={(e) => setIncludeEmeriti(e.target.checked)} />
            Include emeriti
          </label>
          <button
            type="submit"
            disabled={loading || query.trim().length < 2}
            className="ml-auto rounded-xl bg-navy-700 px-5 py-2 text-sm font-semibold text-white shadow-sm hover:bg-navy-800 disabled:opacity-50"
          >
            {loading ? "Searching…" : "Search"}
          </button>
        </div>
        {depts.length === 0 && <p className="mt-2 text-xs text-slate-500">No filter selected: searching all three departments.</p>}
      </form>

      {results === null && !loading && (
        <section className="mt-8 max-w-3xl">
          <p className="text-sm font-medium text-slate-500">Try an example</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => {
                  setQuery(ex);
                  run(ex);
                }}
                className="rounded-lg bg-white px-3 py-2 text-left text-sm text-navy-700 ring-1 ring-slate-200 hover:ring-navy-600"
              >
                {ex}
              </button>
            ))}
          </div>
        </section>
      )}

      {error && <p className="mt-6 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}

      {results && (
        <section className="mt-8 space-y-4" aria-live="polite">
          <p className="text-sm text-slate-500">
            {results.length ? `Top ${results.length} matches` : "No matches."}
            {explaining && " · writing explanations…"}
          </p>
          {results.map((r, i) => (
            <ResultCard key={r.person_key} r={r} rank={i + 1} explaining={explaining} />
          ))}
        </section>
      )}
    </div>
  );
}
