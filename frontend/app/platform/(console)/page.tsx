import type { Metadata } from "next";
import { PlatformOverviewView } from "@/features/platform/overview-view";

export const metadata: Metadata = { title: "Platform overview" };

export default function PlatformOverviewPage() {
  return <PlatformOverviewView />;
}
