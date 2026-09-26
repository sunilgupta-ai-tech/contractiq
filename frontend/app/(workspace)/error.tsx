"use client";

import { CrashScreen } from "@/components/ui/crash-screen";

// Error boundary for every workspace page: keeps the sidebar and top bar,
// and replaces only the crashed page (see components/ui/crash-screen.tsx).
export default function WorkspaceError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <CrashScreen error={error} reset={reset} />;
}
