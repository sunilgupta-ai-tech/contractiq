"use client";

import { useEffect } from "react";
import { newBuildDeployed } from "@/lib/stale-build";

const CHECK_EVERY_MS = 60_000;

/**
 * Prevents "Application error" after a deploy. A tab opened before a new
 * build keeps the old build's code; navigating within the app would then
 * mix old code with the new server's pages and can crash. Once this tab
 * learns a new build is live (checked when the tab regains focus and every
 * minute), in-app links become full page loads, which always fetch
 * matching code.
 */
export function useStaleBuildGuard(): void {
  useEffect(() => {
    let stale = false;
    const check = async () => {
      if (!stale && document.visibilityState === "visible") stale = await newBuildDeployed();
    };
    const onVisible = () => void check();
    const onClick = (event: MouseEvent) => {
      if (!stale || event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!link || link.target === "_blank" || link.origin !== window.location.origin) return;
      event.preventDefault();
      window.location.assign(link.href); // full load of the new build
    };
    const timer = window.setInterval(onVisible, CHECK_EVERY_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    document.addEventListener("click", onClick, true); // capture: before Next's router
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("click", onClick, true);
    };
  }, []);
}
