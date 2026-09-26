import { cn } from "@/utils/cn";

/** "D" monogram set in the display serif, with the DocuNexa AI wordmark. */
export function Logo({ className, withWordmark = true }: { className?: string; withWordmark?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand to-brand/70 font-serif text-[18px] font-semibold leading-none text-white shadow-sm ring-1 ring-white/10">
        D
      </span>
      {withWordmark && (
        <span className="flex items-baseline gap-1.5 font-serif text-[19px] font-medium tracking-tight">
          <span>
            Docu<span className="text-brand">Nexa</span>
          </span>
          <span className="rounded bg-brand-soft px-1 py-px font-sans text-[10px] font-semibold uppercase tracking-[0.08em] text-brand-ink">
            AI
          </span>
        </span>
      )}
    </span>
  );
}
