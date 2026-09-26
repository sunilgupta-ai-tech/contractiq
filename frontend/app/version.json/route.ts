// GET /version.json — the build this server is running, compared by open
// tabs with the build they loaded (lib/stale-build.ts). Never cached.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    { buildId: process.env.NEXT_PUBLIC_BUILD_ID ?? "" },
    { headers: { "Cache-Control": "no-store" } },
  );
}
