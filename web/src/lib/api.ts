/**
 * Typed API client. With USE_MOCKS (the default) everything is served from
 * src/mocks with realistic timing; set VITE_USE_MOCKS=false to talk to the
 * FastAPI backend at VITE_API_BASE (default http://localhost:8000).
 *
 * Endpoint shapes follow docs/SPEC.md §4/§8 and are provisional until the
 * backend's OpenAPI schema lands.
 */
import { MOCK_RECOMMENDATIONS } from "@/mocks/recommendations";
import { FALLBACK_REPLY, SCRIPT, applyPatch, emptyProfile } from "@/mocks/profile";
import { isReady } from "@/lib/profile";
import type {
  EvidenceSource,
  RecommendationSet,
  Session,
  SessionMode,
  StudentProfile,
  TurnEvent,
} from "@/lib/types";

export const USE_MOCKS: boolean = import.meta.env.VITE_USE_MOCKS !== "false";
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function createSession(mode: SessionMode = "text"): Promise<Session> {
  if (USE_MOCKS) return mock.createSession(mode);
  return json<Session>("/sessions", { method: "POST", body: JSON.stringify({ mode }) });
}

/**
 * Send a student turn and stream the counselor's reply.
 * Yields `token` events as text arrives, a `profile` event when extraction
 * finishes (it runs in parallel with the reply), and finally `done`.
 */
export async function* sendTurn(
  sessionId: string,
  text: string,
  source: EvidenceSource = "chat",
  signal?: AbortSignal,
): AsyncGenerator<TurnEvent, void, undefined> {
  if (USE_MOCKS) {
    yield* mock.sendTurn(sessionId, text, source, signal);
    return;
  }
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ text, source }),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await res.text());
  yield* parseSse(res.body);
}

export async function getRecommendations(sessionId: string): Promise<RecommendationSet> {
  if (USE_MOCKS) return mock.getRecommendations(sessionId);
  return json<RecommendationSet>(`/sessions/${sessionId}/recommendations`);
}

/** Voice is mocked in the browser until the WebSocket gateway exists (SPEC §11). */
export const VOICE_AVAILABLE = USE_MOCKS;

/** Mock-only: the next line the scripted student would say, for the fake mic. */
export function mockNextUtterance(sessionId: string): string {
  return mock.nextUtterance(sessionId);
}

// ---------------------------------------------------------------------------
// SSE parsing (event: <type>\ndata: <json>\n\n)
// ---------------------------------------------------------------------------

async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<TurnEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const event = toTurnEvent(raw);
      if (event) yield event;
    }
  }
}

function toTurnEvent(raw: string): TurnEvent | null {
  let type = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  const payload: unknown = data.length ? JSON.parse(data.join("\n")) : {};
  switch (type) {
    case "token":
      return { type, text: (payload as { text: string }).text };
    case "profile":
      return { type, profile: payload as StudentProfile };
    case "recommendations_available":
      return { type };
    case "done":
      return { type, turn_idx: (payload as { turn_idx: number }).turn_idx };
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Aborted", "AbortError"));
    });
  });

interface MockSession {
  step: number;
  turnIdx: number;
  profile: StudentProfile;
}

const mock = (() => {
  const sessions = new Map<string, MockSession>();

  const get = (id: string): MockSession => {
    let s = sessions.get(id);
    if (!s) {
      s = { step: 0, turnIdx: 0, profile: emptyProfile() };
      sessions.set(id, s);
    }
    return s;
  };

  return {
    async createSession(mode: SessionMode): Promise<Session> {
      await sleep(150);
      const id = `mock-${Math.random().toString(36).slice(2, 10)}`;
      get(id);
      return { id, mode, created_at: new Date().toISOString() };
    },

    nextUtterance(sessionId: string): string {
      const s = get(sessionId);
      return SCRIPT[s.step]?.student ?? "Can you show me what you found?";
    },

    async *sendTurn(
      sessionId: string,
      _text: string,
      source: EvidenceSource,
      signal?: AbortSignal,
    ): AsyncGenerator<TurnEvent> {
      const s = get(sessionId);
      const step = SCRIPT[s.step];
      const studentIdx = s.turnIdx + 1;
      s.turnIdx += 2;
      s.step += 1;

      await sleep(650, signal); // time to first token

      const reply = step?.counselor ?? FALLBACK_REPLY;
      const words = reply.split(/(?<=\s)/);
      const half = Math.floor(words.length / 2);
      for (let i = 0; i < words.length; i++) {
        if (i === half && step) {
          // Extraction finishes mid-reply, as it does on the real backend.
          s.profile = applyPatch(s.profile, step.patch, studentIdx, source);
          yield { type: "profile", profile: s.profile };
        }
        yield { type: "token", text: words[i] ?? "" };
        await sleep(38 + Math.random() * 40, signal);
      }
      if (isReady(s.profile)) yield { type: "recommendations_available" };
      yield { type: "done", turn_idx: s.turnIdx };
    },

    async getRecommendations(sessionId: string): Promise<RecommendationSet> {
      await sleep(900);
      return { ...MOCK_RECOMMENDATIONS, session_id: sessionId };
    },
  };
})();
