"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";
import { hasSession } from "@/lib/api-client";
import { useStaleBuildGuard } from "@/hooks/use-stale-build-guard";
import { config } from "@/lib/config";
import { isStaleBuildError, reloadOnce } from "@/lib/stale-build";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const router = useRouter();
  useStaleBuildGuard();

  // With the real API, the workspace needs a signed-in user.
  useEffect(() => {
    if (!config.useDemoData && !hasSession()) router.replace("/login");
  }, [router]);

  // Code that fails to load outside a render (e.g. prefetching the next page)
  // after a new build was deployed: reload once to pick up the new build.
  useEffect(() => {
    const onRejection = (event: PromiseRejectionEvent) => {
      if (isStaleBuildError(event.reason)) reloadOnce();
    };
    const onError = (event: ErrorEvent) => {
      if (isStaleBuildError(event.error)) reloadOnce();
    };
    window.addEventListener("unhandledrejection", onRejection);
    window.addEventListener("error", onError);
    return () => {
      window.removeEventListener("unhandledrejection", onRejection);
      window.removeEventListener("error", onError);
    };
  }, []);

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] lg:block">
        <Sidebar />
      </aside>

      {navOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-rail/60 backdrop-blur-sm" onClick={() => setNavOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[264px] animate-fade-up shadow-lift">
            <Sidebar onNavigate={() => setNavOpen(false)} />
            <button onClick={() => setNavOpen(false)} className="absolute right-3 top-4 rounded-md p-1 text-rail-mute hover:text-rail-ink" aria-label="Close navigation">
              <X className="h-5 w-5" />
            </button>
          </aside>
        </div>
      )}

      <div className="lg:pl-[248px]">
        <Topbar onOpenNav={() => setNavOpen(true)} />
        <main className="mx-auto w-full max-w-[1400px] px-4 py-7 sm:px-6 lg:px-8 lg:py-9">{children}</main>
      </div>
    </div>
  );
}
