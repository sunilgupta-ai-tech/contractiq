import { Activity, FileText, GitCompareArrows, LayoutGrid, MessageSquareText, ShieldAlert, UsersRound, type LucideIcon } from "lucide-react";
import type { Permission } from "@/types";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: string;
  /** Shown only to users with this permission (Phase 17). */
  requires?: Permission;
}

export const primaryNav: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/assistant", label: "Assistant", icon: MessageSquareText, requires: "query:run" },
  { href: "/compare", label: "Compare", icon: GitCompareArrows, requires: "analysis:run" },
  { href: "/risk", label: "Risk review", icon: ShieldAlert, badge: "7", requires: "analysis:run" },
];

export const secondaryNav: NavItem[] = [
  { href: "/team", label: "Team", icon: UsersRound, requires: "user:manage" },
  { href: "/system", label: "System health", icon: Activity },
];
