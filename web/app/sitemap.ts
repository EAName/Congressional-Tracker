import { brand, canonicalUrl } from "@/lib/brand";
import type { MetadataRoute } from "next";

const staticPaths = [
  "/",
  "/analysis",
  "/methodology",
  "/about",
  "/corrections",
  "/race/va-01",
  "/race/va-02",
  "/race/va-05",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return staticPaths.map((path) => ({
    url: canonicalUrl(path),
    lastModified: now,
    changeFrequency: path === "/" ? "daily" : "weekly",
    priority: path === "/" ? 1 : 0.7,
  }));
}

export const dynamic = "force-static";
