import { brand, canonicalUrl } from "@/lib/brand";
import type { MetadataRoute } from "next";

import racesJson from "@/data/races.json";
import type { RacesDoc } from "@/lib/types";

const races = racesJson as RacesDoc;

const staticPaths = [
  "/",
  "/analysis",
  "/methodology",
  "/about",
  "/corrections",
  ...races.races.map((r) => `/race/${r.race_id}`),
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
