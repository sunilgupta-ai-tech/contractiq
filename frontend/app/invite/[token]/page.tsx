import type { Metadata } from "next";
import { AcceptInvitation } from "@/features/auth/accept-invitation";

export const metadata: Metadata = { title: "Join your team", robots: { index: false, follow: false } };

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <AcceptInvitation token={token} />;
}
