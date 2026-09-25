import type { Metadata } from "next";
import { RiskView } from "@/features/risk/risk-view";

export const metadata: Metadata = { title: "Risk review" };
export default function RiskPage() {
  return <RiskView />;
}
