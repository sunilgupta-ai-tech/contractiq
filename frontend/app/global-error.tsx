"use client";

import "./globals.css";
import { CrashScreen } from "@/components/ui/crash-screen";

// Last-resort boundary when the root layout itself fails; it replaces the
// layout, so it renders its own <html> and <body>.
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html lang="en">
      <body>
        <CrashScreen error={error} reset={reset} />
      </body>
    </html>
  );
}
