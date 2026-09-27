"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Building2, LayoutGrid, LogOut, ScrollText, ShieldCheck } from "lucide-react";
import { Logo } from "@/components/ui/logo";
import { hasPlatformSession, PLATFORM_LOGIN, platformSignOut } from "@/lib/platform-client";
import { platformService, type PlatformAdmin } from "@/services/platform-service";
import { cn } from "@/utils/cn";

const PlatformMe = createContext<PlatformAdmin | null>(null);

/** The signed-in platform admin (null while loading). */
export const usePlatformMe = () => useContext(PlatformMe);
export const isSuperAdmin = (me: PlatformAdmin | null) => me?.role === "SUPER_ADMIN";

const NAV = [
  { href: "/platform", label: "Overview", icon: LayoutGrid, superOnly: false },
  { href: "/platform/organizations", label: "Organizations", icon: Building2, superOnly: false },
  { href: "/platform/admins", label: "Platform admins", icon: ShieldCheck, superOnly: true },
  { href: "/platform/audit", label: "Audit log", icon: ScrollText, superOnly: false },
];

/** The platform console frame (Phase 18): its own sign-in guard, navigation
 *  and session — separate from any organization workspace. */
export function PlatformShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<PlatformAdmin | null>(null);

  useEffect(() => {
    if (!hasPlatformSession()) {
      router.replace(PLATFORM_LOGIN);
      return;
    }
    platformService.me().then(setMe).catch(() => undefined); // 401 already redirects
  }, [router]);

  const links = NAV.filter((item) => !item.superOnly || isSuperAdmin(me));
  const active = (href: string) => (href === "/platform" ? pathname === href : pathname.startsWith(href));

  return (
    <PlatformMe.Provider value={me}>
      <div className="min-h-screen lg:pl-[248px]">
        <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] flex-col bg-rail px-3 py-4 text-rail-ink lg:flex">
          <div className="px-2 pb-2 pt-1">
            <Logo className="text-rail-ink" />
          </div>
          <p className="mb-6 px-2 text-2xs font-semibold uppercase tracking-[0.14em] text-[#E8B04B]">Platform console</p>
          <nav className="flex flex-col gap-0.5">
            {links.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex h-9 items-center gap-3 rounded-lg px-3 text-[13.5px] font-medium transition-colors",
                  active(href) ? "bg-rail-2 text-rail-ink" : "text-rail-mute hover:bg-rail-2/60 hover:text-rail-ink",
                )}
              >
                <Icon className={cn("h-[17px] w-[17px]", active(href) ? "text-[#E8B04B]" : "text-rail-mute")} />
                {label}
              </Link>
            ))}
          </nav>
          <div className="mt-auto rounded-xl border border-white/10 p-3">
            <p className="truncate text-[13px] font-medium">{me?.full_name ?? " "}</p>
            <p className="truncate text-2xs text-rail-mute">{me ? `${me.role === "SUPER_ADMIN" ? "Super admin" : "Support"} · ${me.email}` : " "}</p>
            <button
              onClick={() => void platformSignOut()}
              className="mt-3 inline-flex items-center gap-1.5 text-2xs font-medium text-rail-mute hover:text-rail-ink"
            >
              <LogOut className="h-3.5 w-3.5" /> Sign out
            </button>
          </div>
        </aside>

        {/* Small screens: the same links in a scrollable bar. */}
        <header className="sticky top-0 z-20 flex items-center gap-3 overflow-x-auto border-b border-line bg-surface/95 px-4 py-2 backdrop-blur lg:hidden">
          {links.map(({ href, label }) => (
            <Link key={href} href={href} className={cn("shrink-0 rounded-md px-2.5 py-1 text-[13px]", active(href) ? "bg-sunken font-medium text-ink" : "text-ink-2")}>
              {label}
            </Link>
          ))}
          <button onClick={() => void platformSignOut()} className="ml-auto shrink-0 text-[13px] text-ink-2">
            Sign out
          </button>
        </header>

        <main className="mx-auto w-full max-w-[1400px] px-4 py-7 sm:px-6 lg:px-8 lg:py-9">{children}</main>
      </div>
    </PlatformMe.Provider>
  );
}
