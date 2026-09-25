import type { Metadata } from "next";
import { Suspense } from "react";
import { AssistantView } from "@/features/assistant/assistant-view";

export const metadata: Metadata = { title: "Assistant" };

export default function AssistantPage() {
  return (
    <Suspense>
      <AssistantView />
    </Suspense>
  );
}
