import { Keyboard, Mic } from "lucide-react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Atmosphere } from "@/components/Atmosphere";
import { MonoLabel } from "@/components/MonoLabel";
import { Orb } from "@/components/Orb";
import { SiteHeader } from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";

const STEPS = [
  {
    n: "01",
    name: "Talk",
    text: "Say what you love, what you're good at, and what worries you. Speak or type, at your own pace.",
  },
  {
    n: "02",
    name: "Profile",
    text: "Everything the counselor learns appears on screen, tied to your own words, so you can correct it.",
  },
  {
    n: "03",
    name: "Grounded matches",
    text: "Ten colleges and majors, with net price, earnings and graduation rates checked against federal data.",
  },
];

export function Landing() {
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <Atmosphere />
      <SiteHeader />

      <main id="main" className="relative z-10">
        <section className="mx-auto grid min-h-[calc(100dvh-4rem)] max-w-6xl items-center gap-12 px-6 pb-24 pt-8 md:px-8 lg:grid-cols-[1.35fr_1fr] lg:gap-16">
          <div className="order-2 flex flex-col gap-8 lg:order-1">
            <MonoLabel className="rise">A college counselor you can talk to</MonoLabel>
            <h1
              className="rise text-display font-medium text-balance"
              style={{ "--i": 1 } as CSSProperties}
            >
              Talk it through. Find where you fit.
            </h1>
            <p className="rise max-w-[38ch] text-ink-muted text-pretty" style={{ "--i": 2 } as CSSProperties}>
              A quiet conversation about what you love and what you can afford, then colleges matched to you, with every
              number checked against U.S. Department of Education data.
            </p>
            <div className="rise flex flex-wrap items-center gap-3 pt-2" style={{ "--i": 3 } as CSSProperties}>
              <Button asChild size="lg">
                <Link to="/talk?mode=voice">
                  <Mic aria-hidden />
                  Start talking
                </Link>
              </Button>
              <Button asChild size="lg" variant="secondary">
                <Link to="/talk?mode=text">
                  <Keyboard aria-hidden />
                  Type instead
                </Link>
              </Button>
            </div>
          </div>

          <div className="order-1 flex justify-center lg:order-2 lg:justify-end">
            <Orb state="idle" size={320} className="fade-in hidden sm:block" />
            <Orb state="idle" size={168} className="fade-in sm:hidden" />
          </div>
        </section>

        <section aria-labelledby="how" className="mx-auto max-w-6xl px-6 pb-32 md:px-8">
          <MonoLabel as="h2" id="how" muted={false}>
            How it works
          </MonoLabel>
          <ol className="mt-12 grid gap-12 md:grid-cols-3 md:gap-8">
            {STEPS.map((s) => (
              <li key={s.n} className="flex flex-col gap-4 border-t border-line-strong pt-6">
                <MonoLabel>
                  {s.n}
                  <span aria-hidden className="px-[0.6em] text-ink-faint">
                    ·
                  </span>
                  <span className="text-ink">{s.name}</span>
                </MonoLabel>
                <p className="max-w-[34ch] text-ink-muted text-pretty">{s.text}</p>
              </li>
            ))}
          </ol>
        </section>
      </main>

      <footer className="relative z-10 mx-auto flex max-w-6xl flex-col gap-2 border-t border-line px-6 py-8 sm:flex-row sm:items-center sm:justify-between md:px-8">
        <MonoLabel>Data · U.S. Dept. of Education College Scorecard</MonoLabel>
        <MonoLabel>No account needed</MonoLabel>
      </footer>
    </div>
  );
}
