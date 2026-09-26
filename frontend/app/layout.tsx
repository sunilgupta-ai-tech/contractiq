import type { Metadata, Viewport } from "next";
// Fonts are self-hosted from npm (no third-party font requests at runtime).
import "@fontsource-variable/fraunces/full.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";
import { PRODUCT } from "@/lib/product";

export const metadata: Metadata = {
  title: { default: `${PRODUCT.name} — ${PRODUCT.tagline}`, template: `%s · ${PRODUCT.name}` },
  description: PRODUCT.seoDescription,
  applicationName: PRODUCT.name,
  keywords: [...PRODUCT.keywords],
  openGraph: {
    type: "website",
    siteName: PRODUCT.name,
    title: `${PRODUCT.name} — ${PRODUCT.tagline}`,
    description: PRODUCT.seoDescription,
  },
  twitter: {
    card: "summary",
    title: `${PRODUCT.name} — ${PRODUCT.tagline}`,
    description: PRODUCT.seoDescription,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F6F4EF" },
    { media: "(prefers-color-scheme: dark)", color: "#0D1016" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
