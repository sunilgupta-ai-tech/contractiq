"use client";

import { CrashScreen } from "@/components/ui/crash-screen";

// Error boundary for pages outside the workspace (e.g. /login).
export default function RootError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <CrashScreen error={error} reset={reset} />;
}
