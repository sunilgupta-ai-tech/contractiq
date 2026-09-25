import { ContractDetailView } from "@/features/documents/contract-detail-view";

export default async function ContractPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ContractDetailView id={id} />;
}
