import type { Metadata } from "next";
import { SystemView } from "@/features/system/system-view";

export const metadata: Metadata = { title: "System health" };
export default function SystemPage() {
  return <SystemView />;
}
