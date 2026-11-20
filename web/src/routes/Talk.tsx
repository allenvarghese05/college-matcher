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
import { USE_MOCKS, mockNextUtterance, sendTurn } from "@/lib/api";
import { filledCount } from "@/lib/profile";
import { useEnsureSession, useSession } from "@/lib/session";
import type { EvidenceSource, ProfileKey, StudentProfile, VoiceServerEvent } from "@/lib/types";
import { MicMissingError, MicPermissionError, VoiceSession, fetchVoiceStatus, type VoiceUiState } from "@/lib/voice";

/** Mock mode fakes the mic in the browser; live mode streams to WS /api/sessions/{id}/voice. */
const LIVE_VOICE = !USE_MOCKS;

const STATUS: Record<OrbState, string> = {
  idle: "Tap the orb to talk",
  listening: "Listening · tap when you're done",
  thinking: "Thinking",
  speaking: "Speaking",
};

const LIVE_STATUS: Record<VoiceUiState, string> = {
  connecting: "Connecting",
  listening: "Listening · tap the orb to stop",
  thinking: "Thinking",
  speaking: "Speaking",
};

const MIC_BLOCKED =
  "I can't hear you because microphone access is off. You can allow it in your browser's site settings, or keep typing below.";
const MIC_MISSING =
  "I couldn't find a microphone on this device. You can plug one in and tap the orb again, or keep typing below.";

type VoiceAvailability = "unknown" | "available" | "unavailable";

export function Talk() {
  const [params] = useSearchParams();
  const [availability, setAvailability] = useState<VoiceAvailability>(LIVE_VOICE ? "unknown" : "available");
  const voiceAvailable = availability === "available";
  const textMode = params.get("mode") === "text" || !voiceAvailable;
  const navigate = useNavigate();
  const { sessionId, hydrated, turns, setTurns, profile, setProfile, ready, setReady, missing, setMissing } =
    useSession();

  const [orb, setOrb] = useState<OrbState>("idle");
  const [voiceUi, setVoiceUi] = useState<VoiceUiState | null>(null); // null = no live voice session
  const [voiceLevel, setVoiceLevel] = useState<(() => number) | undefined>(undefined);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [interim, setInterim] = useState<string | null>(null);
  const [justLearned, setJustLearned] = useState<ReadonlySet<ProfileKey>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);

  const composerRef = useRef<HTMLInputElement>(null);
  const listenTimer = useRef<number | null>(null);
  const finishTimer = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const voiceRef = useRef<VoiceSession | null>(null);
  const voiceReply = useRef("");
  const voiceDoneTurn = useRef<number | null>(null); // server turn whose reply bubble was added
  const utterance = useRef("");
  const sessionRef = useRef<string | null>(null);
  const profileRef = useRef(profile);
  useEffect(() => {
    profileRef.current = profile;
  }, [profile]);

  // Live mode: ask the backend whether voice is configured (DEEPGRAM_API_KEY).
  useEffect(() => {
    if (!LIVE_VOICE) return;
    const controller = new AbortController();
    void fetchVoiceStatus(controller.signal).then((s) => {
      if (!controller.signal.aborted) setAvailability(s.available ? "available" : "unavailable");
    });
    return () => controller.abort();
  }, []);

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

  // On leaving the page: stop the mic and cancel any reply in flight.
  useEffect(
    () => () => {
      stopListening();
      abortRef.current?.abort();
      voiceRef.current?.stop();
      voiceRef.current = null;
    },
    [stopListening],
  );

  const applyProfile = useCallback(
    (next: StudentProfile) => {
      setJustLearned(changedKeys(profileRef.current, next));
      profileRef.current = next;
      setProfile(next);
    },
    [setProfile],
  );

  const addTurn = useCallback(
    (role: "user" | "assistant", text: string, interrupted = false) => {
      const at = new Date().toISOString();
      setTurns((t) => [...t, { idx: t.length, role, text, interrupted, at }]);
    },
    [setTurns],
  );

  const textBusy = orb === "thinking" || orb === "speaking";
  const voiceBusy = voiceUi === "thinking" || voiceUi === "speaking";

  const runTurn = useCallback(
    async (text: string, source: EvidenceSource) => {
      const id = sessionRef.current;
      if (!id) return;
      setError(null);
      addTurn("user", text);
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
              applyProfile(ev.profile);
              break;
            case "ready":
              setReady(ev.ready);
              setMissing(ev.missing);
              break;
            case "done":
              finalText = ev.assistant_text;
              break;
            case "error":
              // The server's message is written for the student (e.g. a usage limit).
              setError(ev.message?.trim() || "The counselor lost its train of thought. Try saying that again.");
              break;
          }
        }
        const said = (finalText ?? reply).trim();
        if (said) addTurn("assistant", said);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setError("Something interrupted that reply. Try again?");
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setStreaming(null);
        setOrb("idle");
      }
    },
    [addTurn, applyProfile, setReady, setMissing],
  );

  // ------------------------------------------------------------- live voice

  const onVoiceEvent = useCallback(
    (ev: VoiceServerEvent) => {
      switch (ev.type) {
        case "transcript_interim":
          setInterim(ev.text);
          break;
        case "transcript_final":
          setInterim(null);
          setError(null);
          addTurn("user", ev.text);
          voiceReply.current = "";
          break;
        case "assistant_text":
          voiceReply.current += ev.delta;
          setStreaming(voiceReply.current);
          break;
        case "profile":
          applyProfile(ev.profile);
          break;
        case "ready":
          setReady(ev.ready);
          setMissing(ev.missing);
          break;
        case "done": {
          const said = (ev.assistant_text || voiceReply.current).trim();
          if (said) {
            addTurn("assistant", said);
            voiceDoneTurn.current = ev.turn;
          }
          voiceReply.current = "";
          setStreaming(null);
          break;
        }
        case "interrupted":
          // History keeps only what the student actually heard. If the full reply was
          // already shown (audio was still playing), cut that bubble down in place.
          if (voiceDoneTurn.current === ev.turn) {
            setTurns((t) => {
              const i = t.map((x) => x.role).lastIndexOf("assistant");
              const prev = t[i];
              if (!prev) return t;
              const next = [...t];
              next[i] = { ...prev, text: ev.assistant_text, interrupted: true };
              return next;
            });
          } else {
            addTurn("assistant", ev.assistant_text, true);
          }
          voiceDoneTurn.current = ev.turn;
          voiceReply.current = "";
          setStreaming(null);
          break;
        case "error":
          if (!ev.fatal) setError(ev.message);
          break;
        case "metrics":
          if (import.meta.env.DEV) console.debug("[voice] ttfa", ev);
          break;
      }
    },
    [addTurn, applyProfile, setReady, setMissing, setTurns],
  );

  const startVoice = useCallback(async () => {
    const id = sessionRef.current;
    if (!id || voiceRef.current) return;
    setError(null);
    const session = new VoiceSession(id, {
      onUiState: setVoiceUi,
      onEvent: onVoiceEvent,
      onClose: (reason) => {
        if (voiceRef.current === session) voiceRef.current = null;
        setVoiceUi(null);
        setVoiceLevel(undefined);
        setInterim(null);
        if (voiceReply.current) {
          addTurn("assistant", voiceReply.current.trim(), true);
          voiceReply.current = "";
        }
        setStreaming(null);
        if (reason.kind === "error") {
          if (reason.code === "voice_unavailable") setAvailability("unavailable");
          setError(reason.message);
        }
      },
    });
    voiceRef.current = session;
    setVoiceUi("connecting");
    setVoiceLevel(() => session.level);
    try {
      await session.start();
    } catch (e) {
      if (voiceRef.current === session) voiceRef.current = null;
      setVoiceUi(null);
      setVoiceLevel(undefined);
      setError(
        e instanceof MicPermissionError
          ? MIC_BLOCKED
          : e instanceof MicMissingError
            ? MIC_MISSING
            : "I couldn't start the microphone. You can keep typing below.",
      );
    }
  }, [addTurn, onVoiceEvent]);

  // ------------------------------------------------------------- mock voice

  const finishListening = useCallback(() => {
    stopListening();
    const said = utterance.current;
    setInterim(null);
    if (said) void runTurn(said, "voice");
    else setOrb("idle");
  }, [runTurn, stopListening]);

  /** Mock microphone: "hears" the next scripted student line word by word. */
  const startMockListening = (id: string) => {
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

  const onOrbPress = () => {
    const id = sessionRef.current;
    if (!id) return;
    if (LIVE_VOICE) {
      // Tapping toggles the voice session; turn-taking inside it is automatic.
      if (voiceRef.current) voiceRef.current.stop();
      else if (!textBusy) void startVoice();
      return;
    }
    if (textBusy) return;
    if (orb === "listening") finishListening();
    else startMockListening(id);
  };

  // ------------------------------------------------------------- render

  const orbState: OrbState = voiceUi ? (voiceUi === "connecting" ? "thinking" : voiceUi) : orb;
  const status = voiceUi
    ? LIVE_STATUS[voiceUi]
    : !voiceAvailable && orb === "idle"
      ? availability === "unknown"
        ? " "
        : "Voice isn't connected yet"
      : STATUS[orb];
  const orbDisabled = LIVE_VOICE ? !voiceUi && textBusy : textBusy;
  const orbLabel = voiceUi
    ? "End voice conversation"
    : orb === "listening"
      ? "Stop and send"
      : "Talk to the counselor";

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
            {voiceAvailable ? (
              <button
                type="button"
                onClick={onOrbPress}
                aria-disabled={orbDisabled}
                aria-pressed={voiceUi !== null || orb === "listening"}
                aria-label={orbLabel}
                className="rounded-full p-2 transition-transform duration-300 ease-calm active:scale-[0.98] aria-disabled:cursor-default"
              >
                <Orb
                  state={orbState}
                  size={textMode ? 112 : 176}
                  getLevel={voiceUi ? voiceLevel : undefined}
                />
              </button>
            ) : (
              <Orb state={orbState} size={112} />
            )}
            <p aria-live="polite" className="h-4">
              <MonoLabel>{status}</MonoLabel>
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
            busy={textBusy || voiceBusy || orb === "listening" || !hydrated}
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
