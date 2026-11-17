"use client";

import Link from "next/link";

// Shown instead of a bare 500 when a page can't load its data (e.g. the API is asleep or unreachable).
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-16">
      <h1 className="text-2xl font-bold text-navy-800">This page couldn&apos;t load</h1>
      <p className="mt-3 text-slate-600">
        The search server may be waking up (it sleeps when nobody has used it for a while) or briefly unavailable.
        Please try again in a minute.
      </p>
      <div className="mt-6 flex gap-3">
        <button
          onClick={reset}
          className="rounded-xl bg-navy-700 px-5 py-2 text-sm font-semibold text-white hover:bg-navy-800"
        >
          Try again
        </button>
        <Link href="/" className="rounded-xl px-5 py-2 text-sm font-semibold text-navy-700 ring-1 ring-slate-300 hover:ring-navy-600">
          Back to search
        </Link>
      </div>
    </div>
  );
}
