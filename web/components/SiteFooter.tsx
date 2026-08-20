import Link from "next/link";
import type { DisclosureDoc } from "@/lib/types";
import disclosureJson from "@/data/disclosure.json";

const doc = disclosureJson as DisclosureDoc;

export default function SiteFooter() {
  const footer = doc.footer;
  return (
    <footer className="site-foot site-foot-global" aria-label="Site disclosure">
      {footer.paragraphs.map((paragraph) => (
        <p key={paragraph.slice(0, 48)}>{paragraph}</p>
      ))}
      <p>
        <Link href={footer.about_href ?? "/about"}>{footer.about_label ?? "About"}</Link>
        {" · "}
        <Link href={footer.methodology_href}>{footer.methodology_label}</Link>
        {" · "}
        <Link href={footer.corrections_href}>{footer.corrections_label}</Link>
      </p>
    </footer>
  );
}
