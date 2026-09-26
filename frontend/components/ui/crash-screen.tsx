"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, RefreshCw, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { isStaleBuildError, newBuildDeployed, reloadOnce } from "@/lib/stale-build";

/**
 * Shown instead of Next.js's bare "Application error" screen. A crash caused
 * by an outdated build (see lib/stale-build.ts) reloads the page by itself;
 * anything else gets a readable message, a retry, and a reference to quote.
 */
export function CrashScreen({ error, reset }: { error: Error & { digest?: string }; reset?: () => void }) {
  const [reloading, setReloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // An outdated build shows up either as a failed code download or as an
    // arbitrary error from mixing old and new code: in both cases, if the
    // server has a newer build, loading it is the fix.
    const recover = async () => {
      const stale = isStaleBuildError(error) || (await newBuildDeployed());
      if (cancelled) return;
      if (stale && reloadOnce()) setReloading(true);
      else console.error("ContractIQ page error", error);
    };
    void recover();
    return () => {
      cancelled = true;
    };
  }, [error]);

  if (reloading) {
    return (
      <div className="grid min-h-[50vh] place-items-center text-[14px] text-ink-2">
        <span className="flex items-center gap-2">
          <RefreshCw className="h-4 w-4 animate-spin" /> ContractIQ was updated. Loading the new version…
        </span>
      </div>
    );
  }

  return (
    <div className="grid min-h-[50vh] place-items-center px-6">
      <div className="max-w-md text-center">
        <AlertTriangle className="mx-auto mb-3 h-8 w-8 text-warn" />
        <h1 className="display text-[22px]">This page ran into a problem</h1>
        <p className="mt-2 text-[14px] leading-6 text-ink-2">
          Your data is safe. Try again, or reload the page. If it keeps happening, send the reference below to your
          administrator.
        </p>
        <div className="mt-5 flex justify-center gap-2">
          {reset && (
            <Button variant="secondary" onClick={reset}>
              <RotateCcw className="h-4 w-4" /> Try again
            </Button>
          )}
          <Button onClick={() => window.location.reload()}>
            <RefreshCw className="h-4 w-4" /> Reload page
          </Button>
        </div>
        {error.digest && <p className="mt-4 font-mono text-2xs text-ink-3">Reference: {error.digest}</p>}
      </div>
    </div>
  );
}
