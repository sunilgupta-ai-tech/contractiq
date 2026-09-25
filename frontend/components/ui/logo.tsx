import { cn } from "@/utils/cn";

/** Section-sign mark: the legal "§" set in the display serif. */
export function Logo({ className, withWordmark = true }: { className?: string; withWordmark?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand to-brand/70 font-serif text-[19px] leading-none text-white shadow-sm ring-1 ring-white/10">
        §
      </span>
      {withWordmark && (
        <span className="font-serif text-[19px] font-medium tracking-tight">
          Contract<span className="text-brand">IQ</span>
        </span>
      )}
    </span>
  );
}
