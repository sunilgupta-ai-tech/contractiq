import type { Metadata, Viewport } from "next";
// Fonts are self-hosted from npm (no third-party font requests at runtime).
import "@fontsource-variable/fraunces/full.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "ContractIQ", template: "%s · ContractIQ" },
  description: "Enterprise multimodal contract intelligence and agentic RAG.",
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
