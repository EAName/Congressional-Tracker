import { brand, canonicalUrl } from "@/lib/brand";
import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: canonicalUrl("/sitemap.xml"),
    host: brand.canonical_base.replace(/^https?:\/\//, ""),
  };
}
