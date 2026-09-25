"use client";

import { Bell, Menu, Search } from "lucide-react";
import { config } from "@/lib/config";

export function Topbar({ onOpenNav }: { onOpenNav: () => void }) {
  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-canvas/85 px-4 backdrop-blur-md sm:px-6 lg:px-8">
      <button onClick={onOpenNav} className="rounded-lg p-1.5 text-ink-2 hover:bg-sunken lg:hidden" aria-label="Open navigation">
        <Menu className="h-5 w-5" />
      </button>

      <label className="group flex h-9 w-full max-w-md items-center gap-2 rounded-lg border border-line bg-surface px-3 text-ink-3 shadow-card focus-within:border-brand/50">
        <Search className="h-4 w-4 shrink-0" />
        <input
          placeholder="Search contracts, clauses, counterparties…"
          className="w-full bg-transparent text-[13.5px] text-ink placeholder:text-ink-3 focus:outline-none"
        />
        <kbd className="hidden rounded border border-line bg-sunken px-1.5 font-mono text-2xs text-ink-3 sm:block">⌘K</kbd>
      </label>

      <div className="ml-auto flex items-center gap-2">
        {config.useDemoData && (
          <span
            title="Showing sample data until the backend phases for this feature are live"
            className="hidden items-center gap-1.5 rounded-full border border-warn/25 bg-warn-soft px-2.5 py-1 text-2xs font-semibold text-warn sm:inline-flex"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-warn" /> Demo data
          </span>
        )}
        <button className="relative rounded-lg p-2 text-ink-2 hover:bg-sunken" aria-label="Notifications">
          <Bell className="h-[18px] w-[18px]" />
          <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-danger" />
        </button>
        <button className="flex items-center gap-2.5 rounded-lg py-1 pl-1 pr-2 hover:bg-sunken" aria-label="Account">
          <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-soft text-[12px] font-semibold text-brand-ink ring-1 ring-brand/20">
            SG
          </span>
          <span className="hidden text-left leading-tight md:block">
            <span className="block text-[13px] font-medium text-ink">Sunil Gupta</span>
            <span className="block text-2xs text-ink-3">Admin</span>
          </span>
        </button>
      </div>
    </header>
  );
}
