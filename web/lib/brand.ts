import brandJson from "@/data/brand.json";
import type { BrandDoc } from "@/lib/types";

export const brand = brandJson as BrandDoc;

export function pageTitle(suffix: string): string {
  return `${suffix} · ${brand.site_name}`;
}

export function canonicalUrl(path: string): string {
  const base = brand.canonical_base.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}
