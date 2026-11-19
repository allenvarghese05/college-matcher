import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Atmosphere } from "@/components/Atmosphere";
import { MonoLabel } from "@/components/MonoLabel";
import { SiteHeader } from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";
import type { Riasec } from "@/lib/types";

/** Stub of the optional RIASEC quiz (SPEC D10). Items are our own wording. */
const ITEMS: { id: string; code: keyof Riasec; text: string }[] = [
  { id: "q1", code: "R", text: "Taking something apart to see how it works, then putting it back together." },
  { id: "q2", code: "S", text: "Helping a friend talk through a problem until they feel better about it." },
];

const SCALE = ["Not for me", "Not really", "Not sure", "Somewhat", "Love it"];

export function Quiz() {
  const navigate = useNavigate();
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const done = ITEMS.every((i) => answers[i.id] !== undefined);

  return (
    <div className="relative min-h-dvh">
      <Atmosphere intensity="faint" />
      <SiteHeader />
      <main id="main" className="relative z-10 mx-auto flex max-w-3xl flex-col gap-12 px-6 pb-32 pt-12 md:px-8">
        <div className="flex flex-col gap-4">
          <Link
            to="/talk"
            className="mono-label inline-flex items-center gap-2 self-start rounded-sm text-ink-muted transition-colors hover:text-ink"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            Back to the conversation
          </Link>
          <h1 className="text-title font-medium">How much would you enjoy…</h1>
          <p className="text-ink-muted">There are no right answers. Go with your first feeling.</p>
        </div>

        <form
          className="flex flex-col gap-12"
          onSubmit={(e) => {
            e.preventDefault();
            navigate("/talk");
          }}
        >
          {ITEMS.map((item, n) => (
            <fieldset key={item.id} className="flex flex-col gap-6 border-t border-line pt-6">
              <legend className="contents">
                <MonoLabel>
                  {n + 1} of {ITEMS.length}
                </MonoLabel>
                <span className="mt-2 block text-title text-pretty">{item.text}</span>
              </legend>
              <div className="flex flex-wrap gap-2">
                {SCALE.map((label, v) => (
                  <label key={label} className="relative">
                    <input
                      type="radio"
                      name={item.id}
                      value={v}
                      checked={answers[item.id] === v}
                      onChange={() => setAnswers((a) => ({ ...a, [item.id]: v }))}
                      className="peer sr-only"
                    />
                    <span className="inline-flex h-10 cursor-pointer items-center rounded-full border border-line-strong px-4 text-ink-muted transition-colors hover:text-ink peer-checked:border-transparent peer-checked:bg-primary peer-checked:text-primary-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--focus)]">
                      {label}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}

          <div className="flex items-center gap-4 border-t border-line pt-8">
            <Button type="submit" size="lg" disabled={!done}>
              Done
            </Button>
            <MonoLabel>Sample · 2 items</MonoLabel>
          </div>
        </form>
      </main>
    </div>
  );
}
