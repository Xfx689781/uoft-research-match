import type { MetadataRoute } from "next";
import { SITE_URL, listProfessors, professorHref } from "@/lib/api";

export const revalidate = 86400; // rebuilt at most daily
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
