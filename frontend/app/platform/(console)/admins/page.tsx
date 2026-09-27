import type { Metadata } from "next";
import { PlatformAdminsView } from "@/features/platform/admins-view";

export const metadata: Metadata = { title: "Platform admins" };

export default function PlatformAdminsPage() {
  return <PlatformAdminsView />;
}
