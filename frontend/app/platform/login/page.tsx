import type { Metadata } from "next";
import { PlatformLogin } from "@/features/platform/platform-login";

export const metadata: Metadata = { title: "Platform sign-in", robots: { index: false, follow: false } };

export default function PlatformLoginPage() {
  return <PlatformLogin />;
}
