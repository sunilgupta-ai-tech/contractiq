import { OrganizationDetailView } from "@/features/platform/organization-detail-view";

export default async function OrganizationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <OrganizationDetailView id={id} />;
}
