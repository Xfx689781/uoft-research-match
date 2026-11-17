import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import PaperList from "@/components/PaperList";
import { getProfessor, professorHref } from "@/lib/api";

type Props = { params: Promise<{ id: string }> };

export const maxDuration = 120; // Vercel: allow for the free-tier API waking up

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = decodeURIComponent((await params).id);
  const p = await getProfessor(id).catch(() => null);
  if (!p) return { title: "Professor · UofT Research Match" };
  const depts = p.appointments.map((a) => a.department).join(", ");
  const areas = (p.research_areas.length ? p.research_areas : p.topics.map((t) => t.name)).slice(0, 5).join(", ");
  const description =
    `${p.name}, ${p.title}, ${depts}, University of Toronto.` +
    (areas ? ` Research: ${areas}.` : "") +
    (p.papers.length ? ` ${p.papers.length} recent papers, with abstracts and contact info.` : "");
  return {
    title: `${p.name} · UofT Research Match`,
    description,
    alternates: { canonical: professorHref(id) },
    openGraph: { title: `${p.name} · UofT Research Match`, description, type: "profile" },
  };
}

export default async function ProfessorPage({ params }: Props) {
  const p = await getProfessor(decodeURIComponent((await params).id));
  if (!p) notFound();

  const subfields = [...new Set(p.topics.map((t) => t.subfield))].slice(0, 6);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <Link href="/" className="text-sm text-slate-500 hover:text-navy-700">
        ← Back to search
      </Link>

      <header className="mt-4 rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h1 className="text-2xl sm:text-3xl font-bold text-navy-800">{p.name}</h1>
        <ul className="mt-2 space-y-0.5 text-slate-700">
          {p.appointments.map((a) => (
            <li key={a.faculty_id}>
              {a.title} · {a.department}
              {a.home_unit && <span className="text-slate-500"> (home: {a.home_unit})</span>}
            </li>
          ))}
        </ul>

        {(p.is_emeritus || p.accepting_students === false || p.notes.length > 0) && (
          <div className="mt-3 space-y-1">
            {p.is_emeritus && <p className="text-sm text-amber-800">Professor emeritus.</p>}
            {p.notes.map((n) => (
              <p key={n} className="text-sm text-rose-700">
                From the department page: “{n}”
              </p>
            ))}
          </div>
        )}

        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm">
          {p.email && (
            <a href={`mailto:${p.email}`} className="font-medium text-navy-700 hover:underline break-anywhere">
              ✉ {p.email}
            </a>
          )}
          {p.website && (
            <a href={p.website} target="_blank" rel="noreferrer" className="text-navy-700 hover:underline">
              Personal / lab website ↗
            </a>
          )}
          <a href={p.profile_url ?? p.source_url} target="_blank" rel="noreferrer" className="text-navy-700 hover:underline">
            Official department page ↗
          </a>
          {p.openalex_id && (
            <a href={p.openalex_id} target="_blank" rel="noreferrer" className="text-slate-500 hover:underline">
              OpenAlex record ↗
            </a>
          )}
        </div>
      </header>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <aside className="space-y-6 lg:col-span-1">
          {p.research_areas.length > 0 && (
            <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Listed research areas</h2>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {p.research_areas.map((a) => (
                  <span key={a} className="rounded-md bg-navy-50 px-2 py-0.5 text-sm text-navy-700">
                    {a}
                  </span>
                ))}
              </div>
            </section>
          )}
          {p.topics.length > 0 && (
            <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Topics in their papers</h2>
              <p className="mt-1 text-xs text-slate-500">{subfields.join(" · ")}</p>
              <ul className="mt-3 space-y-1.5">
                {p.topics.slice(0, 12).map((t) => (
                  <li key={t.name} className="flex items-center justify-between gap-2 text-sm">
                    <span className="text-slate-700">{t.name}</span>
                    <span className="tabular-nums text-xs text-slate-400">{t.count}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-slate-400">Counts are papers per topic, all years, from OpenAlex.</p>
            </section>
          )}
        </aside>

        <section className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-slate-200 lg:col-span-2">
          <h2 className="text-lg font-semibold text-navy-800">Recent papers (since {new Date().getFullYear() - 6})</h2>
          {p.papers.length ? (
            <div className="mt-3">
              <PaperList papers={p.papers} />
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">
              We couldn&apos;t confidently match this professor to a publication record, so no papers are shown. Check
              their official page or Google Scholar.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
