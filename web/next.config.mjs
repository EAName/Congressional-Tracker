import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const brand = JSON.parse(
  readFileSync(path.join(__dirname, "../config/brand.json"), "utf-8"),
);

const canonicalBase = brand.canonical_base.replace(/\/$/, "");
const legacyHosts = [
  brand.legacy?.old_domain,
  brand.legacy?.old_domain_www,
].filter(Boolean);

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async redirects() {
    const paths = brand.redirect_paths || [];
    const out = [];
    for (const host of legacyHosts) {
      for (const src of paths) {
        out.push({
          source: src,
          has: [{ type: "host", value: host }],
          destination: `${canonicalBase}${src === "/" ? "" : src}`,
          permanent: true,
          statusCode: 308,
        });
      }
    }
    return out;
  },
};

export default nextConfig;
