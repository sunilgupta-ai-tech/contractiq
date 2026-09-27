import type { Metadata } from "next";
import { Suspense } from "react";
import { OrganizationsView } from "@/features/platform/organizations-view";

export const metadata: Metadata = { title: "Organizations" };

export default function OrganizationsPage() {
  // useSearchParams (plan filter from the overview) needs a Suspense boundary.
  return (
    <Suspense>
      <OrganizationsView />
    </Suspense>
  );
}
