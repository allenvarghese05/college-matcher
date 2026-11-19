import { createContext, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { emptyProfile } from "@/mocks/profile";
import type { StudentProfile, TurnOut } from "@/lib/types";

interface SessionState {
  sessionId: string | null;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  turns: TurnOut[];
  setTurns: Dispatch<SetStateAction<TurnOut[]>>;
  ready: boolean;
  setReady: Dispatch<SetStateAction<boolean>>;
  missing: string[];
  setMissing: Dispatch<SetStateAction<string[]>>;
  profile: StudentProfile;
  setProfile: Dispatch<SetStateAction<StudentProfile>>;
}

const Ctx = createContext<SessionState | null>(null);

/** Keeps the conversation alive while the student moves between /talk, /quiz and /results. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<TurnOut[]>([]);
  const [ready, setReady] = useState(false);
  const [missing, setMissing] = useState<string[]>(["home_state", "income_bracket", "interests"]);
  const [profile, setProfile] = useState<StudentProfile>(emptyProfile);

  const value = useMemo(
    () => ({ sessionId, setSessionId, turns, setTurns, ready, setReady, missing, setMissing, profile, setProfile }),
    [sessionId, turns, ready, missing, profile],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): SessionState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside <SessionProvider>");
  return v;
}
