import { ArrowRight } from "lucide-react";
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import type { Field, ProfileKey, StudentProfile } from "@/lib/types";
import { CORE_FIELDS, PANEL_FIELDS, READY_CONFIDENCE, filledCount, formatField, isReady } from "@/lib/profile";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { MonoLabel } from "@/components/MonoLabel";

interface ProfilePanelProps {
  profile: StudentProfile;
  /** Keys learned on the latest turn, for a brief highlight. */
  justLearned?: ReadonlySet<ProfileKey>;
  onShowMatches: () => void;
  className?: string;
}

export function ProfilePanel({ profile, justLearned, onShowMatches, className }: ProfilePanelProps) {
  const ready = isReady(profile);
  const count = filledCount(profile);
  const rows = PANEL_FIELDS.filter(({ key }) => formatField(key, profile[key]) !== null || CORE_FIELDS.includes(key));

  const missing = [
    !known(profile.home_state) && "home state",
    !known(profile.income_bracket) && "family income",
    !known(profile.interests) && !known(profile.intended_majors) && "interests",
  ].filter(Boolean) as string[];

  return (
    <section aria-labelledby="profile-heading" className={cn("flex h-full flex-col", className)}>
      <div className="flex flex-col gap-2">
        <h2 id="profile-heading" className="text-title font-medium">
          What I know so far
        </h2>
        <MonoLabel>{count === 0 ? "Listening for details" : `${count} details · in your words`}</MonoLabel>
      </div>

      <ul className="mt-8 flex flex-col">
        {rows.map(({ key, label }) => (
          <ProfileRow
            key={key}
            label={label}
            value={formatField(key, profile[key])}
            field={profile[key] as Field<unknown>}
            highlight={justLearned?.has(key) ?? false}
          />
        ))}
      </ul>

      <div className="mt-auto flex flex-col gap-4 pt-8">
        <Button size="lg" onClick={onShowMatches} disabled={!ready} className="w-full">
          Show my matches
          <ArrowRight aria-hidden />
        </Button>
        <p className="text-center text-ink-muted" aria-live="polite">
          {ready ? "Ready whenever you are." : `Still need your ${listJoin(missing)}.`}
        </p>
        <Link
          to="/quiz"
          className="self-center rounded-sm text-ink-muted underline decoration-line-strong underline-offset-4 transition-colors hover:text-ink"
        >
          Take the 2-minute interest quiz
        </Link>
      </div>
    </section>
  );
}

function ProfileRow({
  label,
  value,
  field,
  highlight,
}: {
  label: string;
  value: string | null;
  field: Field<unknown>;
  highlight: boolean;
}) {
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const id = useId();
  const quote = field.evidence.at(-1)?.quote;
  const open = (hover || pinned) && !!quote;

  if (value === null) {
    return (
      <li className="flex items-baseline justify-between gap-4 border-t border-line py-3">
        <MonoLabel>{label}</MonoLabel>
        <span className="text-ink-faint" aria-label="Not yet known">
          —
        </span>
      </li>
    );
  }

  return (
    <li className="relative border-t border-line" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setPinned((p) => !p)}
        onBlur={() => setPinned(false)}
        onKeyDown={(e) => e.key === "Escape" && setPinned(false)}
        className={cn(
          "-mx-3 flex w-[calc(100%+1.5rem)] flex-col items-start gap-1 rounded-sm px-3 py-3 text-left transition-colors hover:bg-surface",
          highlight && "just-learned",
        )}
      >
        <MonoLabel>
          {label}
          {field.confidence < READY_CONFIDENCE && <span className="text-ink-faint"> · unsure</span>}
        </MonoLabel>
        <span className="text-ink">{value}</span>
      </button>
      <div
        id={id}
        role="note"
        hidden={!open}
        className="frost fade-in absolute inset-x-0 top-full z-20 -mt-1 rounded-md p-4 shadow-[var(--shadow-soft)]"
      >
        <MonoLabel>You said</MonoLabel>
        <p className="quote mt-1 text-title leading-snug text-ink">“{quote}”</p>
      </div>
    </li>
  );
}

function known(f: Field<unknown>): boolean {
  return f.value !== null && f.confidence >= READY_CONFIDENCE;
}

function listJoin(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}
