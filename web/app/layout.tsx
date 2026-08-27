import type { Metadata } from "next";
import { brand, canonicalUrl } from "@/lib/brand";
import "./globals.css";

// Kept under 155 characters so link cards do not truncate it.
const DESCRIPTION =
  "Race-by-race win probabilities for all 11 Virginia House seats and VA-Sen, updated with a house-effect-corrected generic ballot average.";

const OG_IMAGE_ALT =
  "Win probability for each of Virginia's 11 House districts and the Senate race, with the current generic ballot average.";

export const metadata: Metadata = {
  title: {
    default: brand.site_name,
    template: `%s · ${brand.site_name}`,
  },
  description: DESCRIPTION,
  metadataBase: new URL(brand.canonical_base),
  alternates: {
    canonical: canonicalUrl("/"),
  },
  openGraph: {
    siteName: brand.site_name,
    title: brand.site_name,
    description: DESCRIPTION,
    type: "website",
    url: brand.canonical_base,
    images: [
      {
        url: canonicalUrl("/og/default.png"),
        width: 1200,
        height: 630,
        alt: OG_IMAGE_ALT,
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: brand.site_name,
    description: DESCRIPTION,
    images: [canonicalUrl("/og/default.png")],
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
