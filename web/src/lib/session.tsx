import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { createSession, getSession } from "@/lib/api";
import { emptyProfile, GREETING } from "@/mocks/profile";
import type { SessionMode, SessionState as ServerSessionState, StudentProfile, TurnOut } from "@/lib/types";

const STORAGE_KEY = "cm-session-id";

interface SessionContext {
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  /** True once turns/profile/readiness have been loaded from the server for sessionId. */
  hydrated: boolean;
  hydrate: (state: ServerSessionState) => void;
  turns: TurnOut[];
  setTurns: Dispatch<SetStateAction<TurnOut[]>>;
  ready: boolean;
  setReady: Dispatch<SetStateAction<boolean>>;
  missing: string[];
  setMissing: Dispatch<SetStateAction<string[]>>;
  profile: StudentProfile;
  setProfile: Dispatch<SetStateAction<StudentProfile>>;
}

const Ctx = createContext<SessionContext | null>(null);

function readStoredId(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/**
 * Keeps the conversation alive while the student moves between /talk, /quiz
 * and /results. The session id survives a reload (sessionStorage, this tab
 * only); everything else is rebuilt from GET /api/sessions/{id}.
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionIdState] = useState<string | null>(readStoredId);
  const [hydrated, setHydrated] = useState(false);
  const [turns, setTurns] = useState<TurnOut[]>([]);
  const [ready, setReady] = useState(false);
  const [missing, setMissing] = useState<string[]>(["home_state", "income_bracket", "interests"]);
  const [profile, setProfile] = useState<StudentProfile>(emptyProfile);

  const setSessionId = useCallback((id: string | null) => {
    setSessionIdState(id);
    setHydrated(false);
    try {
      if (id) sessionStorage.setItem(STORAGE_KEY, id);
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* storage unavailable: session lasts for this page load only */
    }
  }, []);

  const hydrate = useCallback((state: ServerSessionState) => {
    setTurns(
      state.turns.length
        ? state.turns
        : [{ idx: 0, role: "assistant", text: GREETING, interrupted: false, at: state.session.created_at }],
    );
    setProfile(state.profile);
    setReady(state.ready);
    setMissing(state.missing);
    setHydrated(true);
  }, []);

  const value = useMemo(
    () => ({
      sessionId,
      setSessionId,
      hydrated,
      hydrate,
      turns,
      setTurns,
      ready,
      setReady,
      missing,
      setMissing,
      profile,
      setProfile,
    }),
    [sessionId, setSessionId, hydrated, hydrate, turns, ready, missing, profile],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): SessionContext {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside <SessionProvider>");
  return v;
}

/**
 * One in-flight open per page load. React StrictMode runs effects twice in
 * dev; both runs share this promise, so no orphan sessions are created.
 */
let opening: Promise<ServerSessionState> | null = null;

function openSession(existingId: string | null, mode: SessionMode, create: boolean): Promise<ServerSessionState> {
  opening ??= (async () => {
    if (existingId) {
      try {
        return await getSession(existingId);
      } catch (e) {
        if (!create) throw e;
        // Stored session is gone (server restarted): start a fresh one.
      }
    }
    const s = await createSession(mode);
    return getSession(s.id);
  })().finally(() => {
    opening = null;
  });
  return opening;
}

/**
 * Make sure the context holds a loaded session. With `create`, a new session is
 * opened when there is none (Talk); without it, only a stored one is restored
 * (Results). Returns an error message for the UI, or null.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useEnsureSession({ create, mode = "text" }: { create: boolean; mode?: SessionMode }): string | null {
  const { sessionId, setSessionId, hydrated, hydrate } = useSession();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (hydrated || (!sessionId && !create)) return;
    let cancelled = false;
    openSession(sessionId, mode, create)
      .then((state) => {
        if (cancelled) return;
        if (state.session.id !== sessionId) setSessionId(state.session.id);
        hydrate(state);
      })
      .catch(() => {
        if (!cancelled) setError("I can't reach the counselor right now. Check your connection and reload.");
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, sessionId, create, mode, setSessionId, hydrate]);

  return error;
}
