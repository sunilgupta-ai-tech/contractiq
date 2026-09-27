import type { Metadata } from "next";
import { PlatformShell } from "@/features/platform/platform-shell";

export const metadata: Metadata = { robots: { index: false, follow: false } };

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return <PlatformShell>{children}</PlatformShell>;
}
