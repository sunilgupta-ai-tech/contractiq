"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronsUpDown } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { cn } from "@/utils/cn";
import { primaryNav, secondaryNav, type NavItem } from "./nav";

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const pathname = usePathname();
  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] font-medium transition-colors",
        active ? "bg-rail-2 text-rail-ink" : "text-rail-mute hover:bg-rail-2/60 hover:text-rail-ink",
      )}
    >
      {active && <span className="absolute -left-3 top-1.5 h-6 w-[3px] rounded-r-full bg-brand" aria-hidden />}
      <Icon className={cn("h-[17px] w-[17px]", active ? "text-brand" : "text-rail-mute group-hover:text-rail-ink")} />
      <span className="flex-1">{item.label}</span>
      {item.badge && (
        <span className="num rounded-md bg-danger/20 px-1.5 text-2xs font-semibold text-[#FF9C92]">{item.badge}</span>
      )}
    </Link>
  );
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col bg-rail px-3 py-4 text-rail-ink">
      <div className="px-2 pb-6 pt-1">
        <Logo className="text-rail-ink" />
      </div>

      <button className="mb-6 flex items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 text-left transition-colors hover:bg-white/[0.06]">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-[#E8B04B] text-[12px] font-bold text-rail">AL</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">Acme Legal</span>
          <span className="block text-2xs text-rail-mute">Organization · 12 seats</span>
        </span>
        <ChevronsUpDown className="h-4 w-4 text-rail-mute" />
      </button>

      <p className="mb-2 px-3 text-2xs font-semibold uppercase tracking-[0.12em] text-rail-mute/70">Workspace</p>
      <nav className="flex flex-col gap-0.5">
        {primaryNav.map((item) => (
          <NavLink key={item.href} item={item} onNavigate={onNavigate} />
        ))}
      </nav>

      <p className="mb-2 mt-7 px-3 text-2xs font-semibold uppercase tracking-[0.12em] text-rail-mute/70">Platform</p>
      <nav className="flex flex-col gap-0.5">
        {secondaryNav.map((item) => (
          <NavLink key={item.href} item={item} onNavigate={onNavigate} />
        ))}
      </nav>

      <div className="mt-auto rounded-xl border border-white/10 bg-gradient-to-b from-white/[0.05] to-transparent p-4">
        <p className="font-serif text-[15px] leading-snug text-rail-ink">Every answer cites its clause.</p>
        <p className="mt-1.5 text-2xs leading-4 text-rail-mute">
          AI-assisted analysis — not legal advice. Review flagged terms with counsel.
        </p>
      </div>
    </div>
  );
}
