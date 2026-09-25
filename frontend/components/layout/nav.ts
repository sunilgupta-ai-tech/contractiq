import { Activity, FileText, GitCompareArrows, LayoutGrid, MessageSquareText, ShieldAlert, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  badge?: string;
}

export const primaryNav: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/documents", label: "Contracts", icon: FileText },
  { href: "/assistant", label: "Assistant", icon: MessageSquareText },
  { href: "/compare", label: "Compare", icon: GitCompareArrows },
  { href: "/risk", label: "Risk review", icon: ShieldAlert, badge: "7" },
];

export const secondaryNav: NavItem[] = [{ href: "/system", label: "System health", icon: Activity }];
