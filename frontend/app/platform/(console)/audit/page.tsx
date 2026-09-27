import type { Metadata } from "next";
import { PlatformAuditView } from "@/features/platform/audit-view";

export const metadata: Metadata = { title: "Platform audit log" };

export default function PlatformAuditPage() {
  return <PlatformAuditView />;
}
