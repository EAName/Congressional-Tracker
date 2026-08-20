import type { Metadata } from "next";
import { brand, canonicalUrl } from "@/lib/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: brand.site_name,
    template: `%s · ${brand.site_name}`,
  },
  description: brand.tagline,
  metadataBase: new URL(brand.canonical_base),
  alternates: {
    canonical: canonicalUrl("/"),
  },
  openGraph: {
    siteName: brand.site_name,
    title: brand.site_name,
    description: brand.tagline,
    type: "website",
    url: brand.canonical_base,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,650;9..144,700&family=Sora:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
