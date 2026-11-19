import { Check } from "lucide-react";
import type { CSSProperties } from "react";
import type { RecommendationView, ScoreBreakdown } from "@/lib/types";
import { CLAIM_LABEL, EARNINGS_CAVEAT, claimValue, visibleClaims } from "@/lib/claims";
import { BandChip } from "@/components/BandChip";
import { MonoLabel } from "@/components/MonoLabel";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

const COMPONENTS: { key: keyof Omit<ScoreBreakdown, "total">; label: string; hint: string }[] = [
  { key: "major_fit", label: "Major fit", hint: "How closely the major matches what you told me" },
  { key: "affordability", label: "Affordability", hint: "Net price at your family's income" },
  { key: "outcomes", label: "Outcomes", hint: "Earnings and debt after graduating" },
  { key: "admission_fit", label: "Admission fit", hint: "Your estimated chances" },
  { key: "preferences", label: "Preferences", hint: "Distance, size and setting" },
];

const BAND_NOTE = {
  safety: "Your scores sit above this school's typical admitted range.",
  target: "Your scores sit within this school's typical admitted range.",
  reach: "Your scores sit below the typical range, or the school is highly selective.",
  unknown: "Share a GPA or test score and I can estimate your chances.",
} as const;

interface WhySheetProps {
  rec: RecommendationView | null;
  dataRelease: string;
  onClose: () => void;
}

export function WhySheet({ rec, dataRelease, onClose }: WhySheetProps) {
  return (
    <Sheet open={rec !== null} onOpenChange={(o) => !o && onClose()}>
      <SheetContent aria-describedby={undefined}>{rec && <Body rec={rec} dataRelease={dataRelease} />}</SheetContent>
    </Sheet>
  );
}

function Body({ rec, dataRelease }: { rec: RecommendationView; dataRelease: string }) {
  const place = claimValue(rec, "city_state");
  const claims = visibleClaims(rec).filter((c) => c.field !== "city_state");
  const s = rec.score_breakdown;

  return (
    <div className="flex h-full flex-col overflow-y-auto overscroll-contain px-6 pb-12 pt-6 md:px-10">
      <header className="flex flex-col gap-4 pr-12">
        <MonoLabel>Why this school</MonoLabel>
        <div className="flex flex-col gap-1">
          <SheetTitle className="text-title font-medium">{rec.institution.name}</SheetTitle>
          <SheetDescription className="text-ink-muted">
            {rec.major?.title ?? "Undecided major"}
            {place && <> · {place}</>}
          </SheetDescription>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <BandChip band={rec.admission_band} />
          <span className="text-ink-muted">{BAND_NOTE[rec.admission_band]}</span>
        </div>
      </header>

      <section aria-labelledby="score-h" className="mt-12">
        <div className="flex items-baseline justify-between">
          <MonoLabel as="h3" id="score-h" muted={false}>
            How it scored
          </MonoLabel>
          <MonoLabel value={pct(s.total)}>Overall</MonoLabel>
        </div>
        <ul className="mt-6 flex flex-col gap-5">
          {COMPONENTS.map(({ key, label, hint }, i) => (
            <li key={key} className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-4">
                <span className="text-ink">
                  {label}
                  <span className="sr-only">, {hint}</span>
                </span>
                <span className="font-mono tabular-nums text-ink-muted">{pct(s[key])}</span>
              </div>
              <div
                role="meter"
                aria-label={label}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(s[key] * 100)}
                className="h-1.5 overflow-hidden rounded-full bg-[var(--bar-track)]"
              >
                <div
                  className="bar-grow h-full origin-left rounded-full bg-[var(--bar-fill)]"
                  style={{ "--v": s[key], "--i": i } as CSSProperties}
                />
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="why-h" className="mt-12">
        <MonoLabel as="h3" id="why-h" muted={false}>
          In short
        </MonoLabel>
        <ul className="mt-4 flex flex-col gap-3">
          {rec.reasons.map((r) => (
            <li key={r} className="text-pretty text-ink">
              {r}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="src-h" className="mt-12">
        <MonoLabel as="h3" id="src-h" muted={false}>
          Sources
        </MonoLabel>
        <ul className="mt-4 flex flex-col">
          {claims.map((c) => (
            <li key={c.field} className="flex items-start justify-between gap-4 border-t border-line py-4">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="text-ink">{CLAIM_LABEL[c.field]}</span>
                <span className="mono-label text-ink-muted">{dataRelease}</span>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className="font-mono tabular-nums text-ink">{c.value}</span>
                <span className="mono-label inline-flex items-center gap-1" style={{ color: "var(--band-safety-ink)" }}>
                  <Check className="size-3" strokeWidth={2.5} aria-hidden />
                  Verified
                </span>
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-6 border-t border-line pt-4 text-ink-muted">{EARNINGS_CAVEAT}</p>
      </section>
    </div>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}`;
