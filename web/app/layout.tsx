import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Virginia Delegation Scorecard",
  description:
    "Signed small-business-climate scores and within-party defections for the Virginia congressional delegation.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
