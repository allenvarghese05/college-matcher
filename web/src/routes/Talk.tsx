import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Atmosphere } from "@/components/Atmosphere";
import { Composer } from "@/components/Composer";
import { MonoLabel } from "@/components/MonoLabel";
import { Orb, type OrbState } from "@/components/Orb";
import { ProfilePanel } from "@/components/ProfilePanel";
import { SiteHeader } from "@/components/SiteHeader";
import { Transcript } from "@/components/Transcript";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { VOICE_AVAILABLE, mockNextUtterance, sendTurn } from "@/lib/api";
import { filledCount } from "@/lib/profile";
import { useEnsureSession, useSession } from "@/lib/session";
import type { EvidenceSource, ProfileKey, StudentProfile } from "@/lib/types";

const STATUS: Record<OrbState, string> = {
  idle: "Tap the orb to talk",
  listening: "Listening · tap when you're done",
  thinking: "Thinking",
  speaking: "Speaking",
};

export function Talk() {
  const [params] = useSearchParams();
  const textMode = params.get("mode") === "text" || !VOICE_AVAILABLE;
  const navigate = useNavigate();
  const { sessionId, hydrated, turns, setTurns, profile, setProfile, ready, setReady, missing, setMissing } =
    useSession();

  const [orb, setOrb] = useState<OrbState>("idle");
  const [streaming, setStreaming] = useState<string | null>(null);
  const [interim, setInterim] = useState<string | null>(null);
  const [justLearned, setJustLearned] = useState<ReadonlySet<ProfileKey>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const composerRef = useRef<HTMLInputElement>(null);
  const listenTimer = useRef<number | null>(null);
  const finishTimer = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const utterance = useRef("");
  const sessionRef = useRef<string | null>(null);
  const profileRef = useRef(profile);
  useEffect(() => {
    profileRef.current = profile;
  }, [profile]);

  const stopListening = useCallback(() => {
    if (listenTimer.current !== null) window.clearInterval(listenTimer.current);
    if (finishTimer.current !== null) window.clearTimeout(finishTimer.current);
    listenTimer.current = null;
    finishTimer.current = null;
  }, []);

  // Open a session, or restore the one stored for this tab, and load its state.
  const openError = useEnsureSession({ create: true, mode: textMode ? "text" : "voice" });
  useEffect(() => {
    sessionRef.current = hydrated ? sessionId : null;
  }, [sessionId, hydrated]);

  useEffect(() => {
    if (textMode) composerRef.current?.focus();
  }, [textMode]);

  // On leaving the page: stop the fake mic and cancel any reply in flight.
  useEffect(
    () => () => {
      stopListening();
      abortRef.current?.abort();
    },
    [stopListening],
  );

  const busy = orb === "thinking" || orb === "speaking";

  const runTurn = useCallback(
    async (text: string, source: EvidenceSource) => {
      const id = sessionRef.current;
      if (!id) return;
      setError(null);
      const at = new Date().toISOString();
      setTurns((t) => [...t, { idx: t.length, role: "user", text, interrupted: false, at }]);
      setOrb("thinking");
      const controller = new AbortController();
      abortRef.current = controller;
      let reply = "";
      let finalText: string | null = null;
      try {
        for await (const ev of sendTurn(id, text, source, controller.signal)) {
          switch (ev.type) {
            case "token":
              if (!reply) setOrb("speaking");
              reply += ev.text;
              setStreaming(reply);
              break;
            case "profile":
              setJustLearned(changedKeys(profileRef.current, ev.profile));
              profileRef.current = ev.profile;
              setProfile(ev.profile);
              break;
            case "ready":
              setReady(ev.ready);
              setMissing(ev.missing);
              break;
            case "done":
              finalText = ev.assistant_text;
              break;
            case "error":
              setError("The counselor lost its train of thought. Try saying that again.");
              break;
          }
        }
        const said = (finalText ?? reply).trim();
        if (said) {
          setTurns((t) => [
            ...t,
            { idx: t.length, role: "assistant", text: said, interrupted: false, at: new Date().toISOString() },
          ]);
        }
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError("Something interrupted that reply. Try again?");
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setStreaming(null);
        setOrb("idle");
      }
    },
    [setTurns, setProfile, setReady, setMissing],
  );

  const finishListening = useCallback(() => {
    stopListening();
    const said = utterance.current;
    setInterim(null);
    if (said) void runTurn(said, "voice");
    else setOrb("idle");
  }, [runTurn, stopListening]);

  /** Mock microphone: "hears" the next scripted student line word by word. */
  const onOrbPress = () => {
    const id = sessionRef.current;
    if (!id || busy) return;
    if (orb === "listening") {
      finishListening();
      return;
    }
    const words = mockNextUtterance(id).split(" ");
    let i = 0;
    utterance.current = words.join(" ");
    setOrb("listening");
    setInterim("");
    listenTimer.current = window.setInterval(() => {
      i += 1;
      setInterim(words.slice(0, i).join(" "));
      if (i >= words.length) {
        if (listenTimer.current !== null) window.clearInterval(listenTimer.current);
        listenTimer.current = null;
        finishTimer.current = window.setTimeout(finishListening, 700);
      }
    }, 170);
  };

  const panel = (
    <ProfilePanel
      profile={profile}
      ready={ready}
      missing={missing}
      justLearned={justLearned}
      onShowMatches={() => navigate("/results")}
    />
  );
  const count = filledCount(profile);

  return (
    <div className="relative flex h-dvh flex-col overflow-hidden">
      <Atmosphere intensity="faint" />
      <SiteHeader>
        <Button variant="ghost" className="lg:hidden" onClick={() => setPanelOpen(true)}>
          What I know
          <span className="mono-label text-ink-muted">{count}</span>
        </Button>
      </SiteHeader>

      <main
        id="main"
        className="relative z-10 mx-auto grid min-h-0 w-full max-w-6xl flex-1 gap-12 px-6 pb-6 md:px-8 lg:grid-cols-[minmax(0,1fr)_340px]"
      >
        <section aria-label="Conversation with the counselor" className="flex min-h-0 flex-col">
          <div className="flex shrink-0 flex-col items-center gap-4 pb-6 pt-2">
            {VOICE_AVAILABLE ? (
              <button
                type="button"
                onClick={onOrbPress}
                aria-disabled={busy}
                aria-pressed={orb === "listening"}
                aria-label={orb === "listening" ? "Stop and send" : "Talk to the counselor"}
                className="rounded-full p-2 transition-transform duration-300 ease-calm active:scale-[0.98] aria-disabled:cursor-default"
              >
                <Orb state={orb} size={textMode ? 112 : 176} />
              </button>
            ) : (
              <Orb state={orb} size={112} />
            )}
            <p aria-live="polite" className="h-4">
              <MonoLabel>
                {VOICE_AVAILABLE ? STATUS[orb] : orb === "idle" ? "Voice isn't connected yet" : STATUS[orb]}
              </MonoLabel>
            </p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto [mask-image:linear-gradient(to_bottom,transparent,black_32px)]">
            <Transcript turns={turns} streaming={streaming} interim={interim} className="mx-auto max-w-2xl pb-4 pt-8" />
          </div>

          {(error ?? openError) && (
            <p role="alert" className="mx-auto w-full max-w-2xl pb-2 text-ink-muted">
              {error ?? openError}
            </p>
          )}
          <Composer
            ref={composerRef}
            onSend={(t) => void runTurn(t, "chat")}
            busy={busy || orb === "listening" || !hydrated}
            className="mx-auto mt-4 w-full max-w-2xl shrink-0"
          />
        </section>

        <aside className="frost hidden min-h-0 overflow-y-auto rounded-lg p-8 lg:my-2 lg:flex lg:flex-col">{panel}</aside>
      </main>

      <Sheet open={panelOpen} onOpenChange={setPanelOpen}>
        <SheetContent side="bottom" aria-describedby={undefined} className="px-6 pb-8 pt-6">
          <SheetTitle className="sr-only">What I know so far</SheetTitle>
          <div className="overflow-y-auto pr-12">{panel}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function changedKeys(prev: StudentProfile, next: StudentProfile): ReadonlySet<ProfileKey> {
  const keys = Object.keys(next) as ProfileKey[];
  return new Set(keys.filter((k) => JSON.stringify(prev[k].value) !== JSON.stringify(next[k].value)));
}
