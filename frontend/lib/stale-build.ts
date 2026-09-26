// After a new frontend build is deployed, a tab that was opened before it
// still references the old build's JavaScript files, which no longer exist.
// The next client-side navigation then fails to load code ("ChunkLoadError")
// and the page crashes; a refresh fixes it because it loads the new build.
// This does that refresh automatically — once, so a genuinely broken page
// can never cause a reload loop.

const RELOAD_KEY = "ciq.stale-build-reload";
const LOOP_GUARD_MS = 30_000;

export function isStaleBuildError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.name === "ChunkLoadError" ||
    /Loading (CSS )?chunk [\w-]+ failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(
      error.message,
    )
  );
}

/** Reload the page to pick up the new build. Returns false (and does nothing)
 *  if we already reloaded for this reason moments ago. */
export function reloadOnce(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_KEY) ?? 0);
    if (Date.now() - last < LOOP_GUARD_MS) return false;
    window.sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    // Storage unavailable: reload anyway; a second failure shows the error page.
  }
  window.location.reload();
  return true;
}

/** The build this tab is running (compiled in at build time). */
export const CLIENT_BUILD_ID = process.env.NEXT_PUBLIC_BUILD_ID ?? "";

/** True when the server now runs a different build than this tab loaded.
 *  Errors (offline, server restarting) count as "not known to be stale". */
export async function newBuildDeployed(clientBuildId: string = CLIENT_BUILD_ID): Promise<boolean> {
  if (!clientBuildId) return false;
  try {
    const response = await fetch("/version.json", { cache: "no-store" });
    if (!response.ok) return false;
    const { buildId } = (await response.json()) as { buildId?: string };
    return Boolean(buildId) && buildId !== clientBuildId;
  } catch {
    return false;
  }
}
