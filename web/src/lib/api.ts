/**
 * Typed API client for the routes in backend/app/schemas.py (prefix /api).
 * With USE_MOCKS (the default) everything is served from src/mocks with
 * realistic timing; set VITE_USE_MOCKS=false to talk to the FastAPI backend
 * at VITE_API_BASE (default http://localhost:8000).
 */
import { MOCK_RECOMMENDATIONS } from "@/mocks/recommendations";
import { FALLBACK_REPLY, GREETING, SCRIPT, applyPatch, emptyProfile } from "@/mocks/profile";
import { missingForRecommendation } from "@/lib/profile";
import type {
  EvidenceSource,
  RecommendRequest,
  RecommendationSet,
  SessionCreate,
  SessionMode,
  SessionOut,
  SessionState,
  StudentProfile,
  TurnEvent,
  TurnIn,
  TurnOut,
} from "@/lib/types";

export const USE_MOCKS: boolean = import.meta.env.VITE_USE_MOCKS !== "false";
export const API_BASE: string = `${import.meta.env.VITE_API_BASE ?? "http://localhost:8000"}/api`;

/** Data release every claim is checked against (shown in "Sources"). */
export const DATA_RELEASE = "College Scorecard, 2026 release";

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

export async function createSession(mode: SessionMode = "text"): Promise<SessionOut> {
  if (USE_MOCKS) return mock.createSession(mode);
  const body: SessionCreate = { mode };
  return json<SessionOut>("/sessions", { method: "POST", body: JSON.stringify(body) });
}

export async function getSession(sessionId: string): Promise<SessionState> {
  if (USE_MOCKS) return mock.getSession(sessionId);
  return json<SessionState>(`/sessions/${sessionId}`);
}

/**
 * Send a student turn and stream the counselor's reply as TurnEvents.
 * `source` stays client-side (it only feeds the mock extractor): TurnIn is
 * strict on the server and rejects any key but `text`.
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
  const body: TurnIn = { text };
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/turns`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) throw new ApiError(res.status, await res.text());
  yield* parseSse(res.body);
}

export async function getRecommendations(
  sessionId: string,
  request: RecommendRequest = {},
): Promise<RecommendationSet> {
  if (USE_MOCKS) return mock.getRecommendations(sessionId);
  return json<RecommendationSet>(`/sessions/${sessionId}/recommendations`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** Voice is mocked in the browser until the WebSocket gateway exists (SPEC §11). */
export const VOICE_AVAILABLE = USE_MOCKS;

/** Mock-only: the next line the scripted student would say, for the fake mic. */
export function mockNextUtterance(sessionId: string): string {
  return mock.nextUtterance(sessionId);
}

// ---------------------------------------------------------------------------
// SSE parsing (event: <name>\ndata: <json>\n\n)
// ---------------------------------------------------------------------------

async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<TurnEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      // A chunk may end between "\r" and "\n" (sse-starlette uses CRLF). Hold a
      // trailing "\r" until the next chunk so the pair normalises to one "\n".
      let held = "";
      if (!done && buffer.endsWith("\r")) {
        held = "\r";
        buffer = buffer.slice(0, -1);
      }
      buffer = buffer.replace(/\r\n?/g, "\n");
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const event = toTurnEvent(buffer.slice(0, sep));
        buffer = buffer.slice(sep + 2);
        if (event) yield event;
      }
      buffer += held;
      if (done) {
        const tail = buffer.trim() ? toTurnEvent(buffer) : null;
        if (tail) yield tail;
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

function toTurnEvent(raw: string): TurnEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  let parsed: unknown;
  try {
    parsed = data.length ? JSON.parse(data.join("\n")) : {};
  } catch {
    return null; // a malformed frame should not kill the stream
  }
  if (!isObject(parsed)) return null;
  const p = parsed;
  switch (name) {
    case "token":
      return typeof p.text === "string" ? { type: "token", text: p.text } : null;
    case "profile":
      return isObject(p.profile) ? { type: "profile", profile: p.profile as unknown as StudentProfile } : null;
    case "ready":
      return {
        type: "ready",
        ready: p.ready === true,
        missing: Array.isArray(p.missing) ? p.missing.filter((m): m is string => typeof m === "string") : [],
      };
    case "done":
      return { type: "done", turn_id: String(p.turn_id ?? ""), assistant_text: String(p.assistant_text ?? "") };
    case "error":
      return { type: "error", message: String(p.message ?? "") };
    default:
      return null;
  }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });

interface MockSession {
  session: SessionOut;
  step: number;
  profile: StudentProfile;
  turns: TurnOut[];
}

const mock = (() => {
  const sessions = new Map<string, MockSession>();
  const now = () => new Date().toISOString();

  const get = (id: string): MockSession => {
    let s = sessions.get(id);
    if (!s) {
      s = {
        session: { id, mode: "text", created_at: now() },
        step: 0,
        profile: emptyProfile(),
        turns: [{ idx: 0, role: "assistant", text: GREETING, interrupted: false, at: now() }],
      };
      sessions.set(id, s);
    }
    return s;
  };

  return {
    async createSession(mode: SessionMode): Promise<SessionOut> {
      await sleep(150);
      const id = `mock-${Math.random().toString(36).slice(2, 10)}`;
      const s = get(id);
      s.session.mode = mode;
      return s.session;
    },

    async getSession(id: string): Promise<SessionState> {
      await sleep(80);
      const s = get(id);
      const missing = missingForRecommendation(s.profile);
      return { session: s.session, profile: s.profile, turns: s.turns, ready: missing.length === 0, missing };
    },

    nextUtterance(sessionId: string): string {
      return SCRIPT[get(sessionId).step]?.student ?? "Can you show me what you found?";
    },

    async *sendTurn(
      sessionId: string,
      text: string,
      source: EvidenceSource,
      signal?: AbortSignal,
    ): AsyncGenerator<TurnEvent> {
      const s = get(sessionId);
      const step = SCRIPT[s.step];
      const studentIdx = s.turns.length;
      s.turns.push({ idx: studentIdx, role: "user", text, interrupted: false, at: now() });
      s.step += 1;

      await sleep(650, signal); // time to first token

      const reply = step?.counselor ?? FALLBACK_REPLY;
      const words = reply.split(/(?<=\s)/);
      const half = Math.floor(words.length / 2);
      for (let i = 0; i < words.length; i++) {
        if (i === half && step) {
          // Extraction finishes mid-reply, as on the real backend.
          s.profile = applyPatch(s.profile, step.patch, studentIdx, source);
          yield { type: "profile", profile: s.profile };
          const missing = missingForRecommendation(s.profile);
          yield { type: "ready", ready: missing.length === 0, missing };
        }
        yield { type: "token", text: words[i] ?? "" };
        await sleep(38 + Math.random() * 40, signal);
      }
      s.turns.push({ idx: s.turns.length, role: "assistant", text: reply, interrupted: false, at: now() });
      yield { type: "done", turn_id: `mock-turn-${s.turns.length}`, assistant_text: reply };
    },

    async getRecommendations(sessionId: string): Promise<RecommendationSet> {
      await sleep(400);
      return { ...MOCK_RECOMMENDATIONS, session_id: sessionId };
    },
  };
})();
