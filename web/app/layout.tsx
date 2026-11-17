import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Link from "next/link";
import { SITE_URL, formatDate, getMeta } from "@/lib/api";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

const description =
  "Find a research supervisor at the University of Toronto: describe your interests and get Computer Science, " +
  "Mathematics and Statistics professors whose recent papers match, with the papers and contact info.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "UofT Research Match: find a research supervisor at the University of Toronto",
  description,
  keywords: ["UofT", "University of Toronto", "research supervisor", "undergraduate research", "professors",
    "computer science", "mathematics", "statistics", "research match"],
  alternates: { canonical: "/" },
  openGraph: { title: "UofT Research Match", description, type: "website", siteName: "UofT Research Match" },
  // Google Search Console: set GOOGLE_SITE_VERIFICATION in Vercel to the code Google gives you
  verification: process.env.GOOGLE_SITE_VERIFICATION ? { google: process.env.GOOGLE_SITE_VERIFICATION } : undefined,
};

export default async function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const meta = await getMeta();
  return (
    <html lang="en">
      <body className={`${inter.variable} font-sans antialiased min-h-screen flex flex-col`}>
        <header className="bg-navy-700 text-white">
          <div className="mx-auto max-w-5xl px-4 py-3 flex items-center justify-between gap-4">
            <Link href="/" className="font-semibold tracking-tight text-lg">
              UofT Research Match
            </Link>
            <span className="text-xs text-navy-100 hidden sm:block">
              Computer Science · Mathematics · Statistical Sciences
            </span>
          </div>
        </header>

        <main className="flex-1">{children}</main>

        <footer className="border-t border-slate-200 bg-white">
          <div className="mx-auto max-w-5xl px-4 py-6 text-xs text-slate-500 space-y-2">
            <p>
              <strong className="text-slate-700">Always verify on the official profile page</strong> before
              contacting anyone. Information here is collected automatically from public department directories
              and OpenAlex, and can be out of date or wrong (e.g. a paper attributed to the wrong person).
            </p>
            <p>
              Data last updated: {formatDate(meta?.data_last_updated)}
              {meta && ` · ${meta.searchable_professors} searchable faculty`}
              {meta?.explanations === "claude" && " · match explanations written by Claude"}
            </p>
            <p>Not affiliated with or endorsed by the University of Toronto.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
