import { createContext, useContext, useMemo, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { emptyProfile } from "@/mocks/profile";
import type { StudentProfile, Turn } from "@/lib/types";

interface SessionState {
  sessionId: string | null;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  turns: Turn[];
  setTurns: Dispatch<SetStateAction<Turn[]>>;
  profile: StudentProfile;
  setProfile: Dispatch<SetStateAction<StudentProfile>>;
}

const Ctx = createContext<SessionState | null>(null);

/** Keeps the conversation alive while the student moves between /talk, /quiz and /results. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [profile, setProfile] = useState<StudentProfile>(emptyProfile);

  const value = useMemo(
    () => ({ sessionId, setSessionId, turns, setTurns, profile, setProfile }),
    [sessionId, turns, profile],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession(): SessionState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used inside <SessionProvider>");
  return v;
}
