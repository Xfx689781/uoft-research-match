import type { MetadataRoute } from "next";
import { SITE_URL, listProfessors, professorHref } from "@/lib/api";

// Rendered per request; the professor list itself is cached for a day (lib/api listProfessors), and a failed
// fetch is not cached, so a sitemap built while the API was down doesn't stick around.
export const dynamic = "force-dynamic";
export const maxDuration = 120;

// Lets search engines find every professor page, not only the home page.
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const home = { url: `${SITE_URL}/`, changeFrequency: "weekly" as const, priority: 1 };
  try {
    const profs = await listProfessors();
    return [
      home,
      ...profs.map((p) => ({ url: `${SITE_URL}${professorHref(p.id)}`, changeFrequency: "monthly" as const, priority: 0.6 })),
    ];
  } catch {
    return [home];
  }
}
