import { ArrowUpRight } from "lucide-react";
import type { CSSProperties } from "react";
import type { RecommendationOut } from "@/lib/types";
import { keyNumbers, place as placeOf } from "@/lib/claims";
import { BandChip } from "@/components/BandChip";
import { MonoLabel } from "@/components/MonoLabel";

interface SchoolCardProps {
  rec: RecommendationOut;
  onOpen: (rec: RecommendationOut) => void;
  index?: number;
}

/**
 * One recommendation. The school name is the real button; its ::after
 * stretches over the card so the whole surface is clickable while the
 * markup stays valid and screen readers hear a single control.
 */
export function SchoolCard({ rec, onOpen, index = 0 }: SchoolCardProps) {
  const place = placeOf(rec);
  const numbers = keyNumbers(rec);

  return (
    <article
      className="rise group frost relative flex flex-col gap-6 rounded-lg p-6 transition-[box-shadow,transform] duration-300 ease-calm hover:-translate-y-0.5 hover:shadow-[var(--shadow-soft)] has-[button:focus-visible]:outline has-[button:focus-visible]:outline-2 has-[button:focus-visible]:outline-offset-2 has-[button:focus-visible]:outline-[var(--focus)] md:p-8"
      style={{ "--i": index } as CSSProperties}
    >
      <div className="flex items-center justify-between gap-4">
        <MonoLabel>{String(rec.rank).padStart(2, "0")}</MonoLabel>
        <BandChip band={rec.admission_band} low={rec.band_confidence === "low"} />
      </div>

      <div className="flex flex-col gap-1">
        <h3 className="text-title font-medium">
          <button
            type="button"
            onClick={() => onOpen(rec)}
            className="text-left after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:outline-none"
          >
            {rec.name}
            <span className="sr-only">: why this school</span>
          </button>
        </h3>
        <p className="text-ink-muted">
          {rec.cip_title ?? "Undecided major"}
          {place && (
            <>
              <span aria-hidden className="px-2 text-ink-faint">
                ·
              </span>
              {place}
            </>
          )}
        </p>
      </div>

      <dl className="grid grid-cols-3 gap-4 border-y border-line py-4">
        {numbers.map((n) => (
          <div key={n.field} className="flex min-w-0 flex-col gap-1">
            <dt className="mono-label text-ink-muted">{n.label}</dt>
            <dd className="flex flex-col gap-0.5">
              <span className="font-mono text-body tabular-nums tracking-[-0.02em] text-ink">{n.value}</span>
              {n.note && <span className="mono-label text-ink-faint">{n.note}</span>}
            </dd>
          </div>
        ))}
      </dl>

      <p className="text-pretty text-ink-muted">{rec.reasons.join(" ")}</p>

      <span
        aria-hidden
        className="mono-label inline-flex items-center gap-1 self-end text-ink-muted transition-colors group-hover:text-ink"
      >
        Why this school
        <ArrowUpRight className="size-3.5 transition-transform duration-300 ease-calm group-hover:-translate-y-px group-hover:translate-x-px" />
      </span>
    </article>
  );
}
