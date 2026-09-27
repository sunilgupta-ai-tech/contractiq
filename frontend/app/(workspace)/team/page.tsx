import type { Metadata } from "next";
import { TeamView } from "@/features/team/team-view";

export const metadata: Metadata = { title: "Team" };

export default function TeamPage() {
  return <TeamView />;
}
