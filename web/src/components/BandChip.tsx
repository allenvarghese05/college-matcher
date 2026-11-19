import type { AdmissionBand } from "@/lib/types";
import { cn } from "@/lib/utils";

const LABEL: Record<AdmissionBand, string> = {
  safety: "Safety",
  target: "Target",
  reach: "Reach",
  unknown: "Unknown",
};

/** Admission band, always labelled "estimated" (SPEC D9, §13). */
export function BandChip({ band, className }: { band: AdmissionBand; className?: string }) {
  return (
    <span
      className={cn("mono-label inline-flex h-6 items-center gap-[0.5em] rounded-full px-2.5", className)}
      style={{ background: `var(--band-${band}-bg)`, color: `var(--band-${band}-ink)` }}
    >
      <span className="opacity-75">Est.</span>
      <span aria-hidden>·</span>
      <span>{LABEL[band]}</span>
      <span className="sr-only"> (estimated admission chance)</span>
    </span>
  );
}
