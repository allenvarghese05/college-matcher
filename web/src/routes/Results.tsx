import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { Atmosphere } from "@/components/Atmosphere";
import { MonoLabel } from "@/components/MonoLabel";
import { Orb } from "@/components/Orb";
import { SchoolCard } from "@/components/SchoolCard";
import { SiteHeader } from "@/components/SiteHeader";
import { WhySheet } from "@/components/WhySheet";
import { Button } from "@/components/ui/button";
import { DATA_RELEASE, USE_MOCKS, getRecommendations } from "@/lib/api";
import { EARNINGS_CAVEAT } from "@/lib/claims";
import { useEnsureSession, useSession } from "@/lib/session";
import type { AdmissionBand, RecommendationSet, RecommendationOut } from "@/lib/types";

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; set: RecommendationSet };

const WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];

export function Results() {
  const { sessionId } = useSession();
  // After a reload, rebuild the conversation context from the stored session id
  // so "Refine with the counselor" lands back in the same conversation.
  useEnsureSession({ create: false });
  const id = sessionId ?? (USE_MOCKS ? "mock-session" : null);
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [open, setOpen] = useState<RecommendationOut | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getRecommendations(id)
      .then((set) => !cancelled && setLoad({ status: "ready", set }))
      .catch(() => !cancelled && setLoad({ status: "error", message: "I couldn't load your matches just now." }));
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <div className="relative min-h-dvh">
      <Atmosphere intensity="faint" />
      <SiteHeader />
      <main id="main" className="relative z-10 mx-auto max-w-6xl px-6 pb-32 pt-12 md:px-8">
        {!id ? (
          <Empty />
        ) : load.status === "loading" ? (
          <Loading />
        ) : load.status === "error" ? (
          <ErrorState message={load.message} />
        ) : (
          <Ready set={load.set} onOpen={setOpen} />
        )}
      </main>
      {load.status === "ready" && (
        <WhySheet rec={open} dataRelease={DATA_RELEASE} onClose={() => setOpen(null)} />
      )}
    </div>
  );
}

function Ready({ set, onOpen }: { set: RecommendationSet; onOpen: (r: RecommendationOut) => void }) {
  const recs = set.recommendations;
  const mix = useMemo(() => bandMix(recs), [recs]);
  const n = recs.length;

  return (
    <>
      <header className="flex flex-col gap-8 pb-16">
        <MonoLabel className="rise">{mix}</MonoLabel>
        <h1 className="rise max-w-[14ch] text-display font-medium text-balance" style={{ "--i": 1 } as CSSProperties}>
          {WORDS[n] ?? n} places worth a closer look.
        </h1>
        <div
          className="rise flex flex-col gap-6 md:flex-row md:items-end md:justify-between"
          style={{ "--i": 2 } as CSSProperties}
        >
          <div className="flex max-w-[52ch] flex-col gap-2">
            <p className="text-ink-muted text-pretty">
              Ranked for your interests, budget and grades. Every number is checked against the College Scorecard;
              chances are estimates, not predictions.
            </p>
            <p className="text-ink-muted">{EARNINGS_CAVEAT}</p>
          </div>
          <Button asChild variant="secondary" className="self-start md:self-auto">
            <Link to="/talk">
              <ArrowLeft aria-hidden />
              Refine with the counselor
            </Link>
          </Button>
        </div>
      </header>

      <section aria-label="Recommended colleges">
        <ol className="grid gap-6 lg:grid-cols-2">
          {recs.map((r, i) => (
            <li key={r.unitid} className="flex">
              <SchoolCard rec={r} index={i} onOpen={onOpen} />
            </li>
          ))}
        </ol>
      </section>
    </>
  );
}

function Loading() {
  return (
    <div className="flex flex-col items-center gap-6 py-32 text-center" role="status">
      <Orb state="thinking" size={120} />
      <MonoLabel>Checking every number against the Scorecard</MonoLabel>
    </div>
  );
}

function Empty() {
  return (
    <div className="flex flex-col items-start gap-6 py-24">
      <MonoLabel>No matches yet</MonoLabel>
      <h1 className="text-title font-medium">Talk with the counselor first, and your matches will appear here.</h1>
      <Button asChild>
        <Link to="/talk">Start talking</Link>
      </Button>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-6 py-24">
      <MonoLabel>Something went wrong</MonoLabel>
      <h1 className="text-title font-medium">{message}</h1>
      <Button variant="secondary" onClick={() => window.location.reload()}>
        Try again
      </Button>
    </div>
  );
}

function bandMix(recs: RecommendationOut[]): string {
  const order: AdmissionBand[] = ["safety", "target", "reach", "unknown"];
  const counts = order
    .map((b) => [b, recs.filter((r) => r.admission_band === b).length] as const)
    .filter(([, c]) => c > 0)
    .map(([b, c]) => `${c} ${b}`);
  return `${recs.length} matches · ${counts.join(" · ")} · estimated`;
}
