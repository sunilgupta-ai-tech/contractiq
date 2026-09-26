import { FileImage, FileSpreadsheet, FileText, FileType2, ScanText, type LucideIcon } from "lucide-react";
import type { ContractDocument, FileType } from "@/types";
import { cn } from "@/utils/cn";

/** Labels, icon and colour per file type, shared by the library tabs and rows. */
export const FILE_TYPE_META: Record<FileType, { label: string; plural: string; icon: LucideIcon; tint: string }> = {
  PDF: { label: "PDF", plural: "PDF", icon: FileText, tint: "text-danger bg-danger-soft" },
  IMAGE: { label: "Image", plural: "Images", icon: FileImage, tint: "text-info bg-info-soft" },
  WORD: { label: "Word", plural: "Word", icon: FileType2, tint: "text-brand-ink bg-brand-soft" },
  EXCEL: { label: "Excel", plural: "Excel", icon: FileSpreadsheet, tint: "text-ok bg-ok-soft" },
};

/** "PDF", "Scanned PDF", "Image", … */
export function fileTypeLabel(doc: Pick<ContractDocument, "fileType" | "isScanned">): string {
  return doc.fileType === "PDF" && doc.isScanned ? "Scanned PDF" : FILE_TYPE_META[doc.fileType].label;
}

export function FileTypeIcon({ doc, className }: { doc: Pick<ContractDocument, "fileType" | "isScanned">; className?: string }) {
  const meta = FILE_TYPE_META[doc.fileType];
  const Icon = doc.fileType === "PDF" && doc.isScanned ? ScanText : meta.icon;
  return (
    <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-lg", meta.tint, className)}>
      <Icon className="h-4 w-4" />
    </span>
  );
}
