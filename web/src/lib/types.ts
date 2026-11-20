/**
 * Hand-written mirror of backend/app/schemas.py (the source of truth, SPEC §6).
 *
 * TEMPORARY: replace with types generated from the FastAPI OpenAPI schema.
 * Names and shapes are 1:1 with the Pydantic models so the swap is mechanical.
 * UUIDs and datetimes arrive as strings.
 */

// ------------------------------------------------------------------ enums

export type IncomeBracket = "0-30k" | "30-48k" | "48-75k" | "75-110k" | "110k+";
export type EvidenceSource = "chat" | "voice" | "resume" | "quiz";
export type SizePref = "small" | "medium" | "large" | "any";
export type SettingPref = "city" | "suburb" | "town" | "rural" | "any";
export type Priority = "cost" | "outcomes" | "prestige" | "location" | "fit";
export type WorkValue =
  | "achievement"
  | "independence"
  | "recognition"
  | "relationships"
  | "support"
  | "working_conditions";
export type AdmissionBand = "safety" | "target" | "reach" | "unknown";
export type BandConfidence = "normal" | "low";
/**
 * How a recommendation's net price was derived (backend app/retrieval/pricing.py):
 * in_state / private = Scorecard net price at the student's income;
 * est_out_of_state = that price + (out-of-state - in-state tuition) at a public
 * school outside the home state; unknown = not reported for this student.
 */
export type NetPriceBasis = "in_state" | "est_out_of_state" | "private" | "unknown";
export type SessionMode = "text" | "voice";
export type RetrievalMode = "sql_only" | "hybrid" | "hybrid_rerank" | "hybrid_riasec_rerank";

// ---------------------------------------------------------------- profile

export interface Evidence {
  /** The student's exact words supporting this value. */
  quote: string;
  turn_idx: number;
  source: EvidenceSource;
}

export interface ProfileField<T> {
  value: T | null;
  /** 0..1 */
  confidence: number;
  evidence: Evidence[];
}

export interface Activity {
  name: string;
  role: string | null;
  years: number | null;
  hours_per_week: number | null;
}

/** Holland interest profile, each dimension 0..1. */
export interface Riasec {
  R: number;
  I: number;
  A: number;
  S: number;
  E: number;
  C: number;
}

export interface StudentProfile {
  home_state: ProfileField<string>; // USPS code
  home_zip: ProfileField<string>;
  gpa: ProfileField<number>; // unweighted 0-4
  sat: ProfileField<number>; // 400-1600
  act: ProfileField<number>; // 1-36
  income_bracket: ProfileField<IncomeBracket>;
  budget_cap: ProfileField<number>; // $/year
  interests: ProfileField<string[]>;
  dream_without_money: ProfileField<string>;
  intended_majors: ProfileField<string[]>;
  riasec: ProfileField<Riasec>;
  strengths: ProfileField<string[]>;
  favorite_subjects: ProfileField<string[]>;
  activities: ProfileField<Activity[]>;
  work_values: ProfileField<WorkValue[]>;
  max_distance_miles: ProfileField<number>;
  /** Fixed vocabulary: Census regions/divisions, USPS codes, "out_of_state". */
  regions: ProfileField<string[]>;
  size_pref: ProfileField<SizePref>;
  setting_pref: ProfileField<SettingPref>;
  priorities: ProfileField<Priority[]>;
}

export type ProfileKey = keyof StudentProfile;

// ------------------------------------------------------- retrieval / recs

/** Each component 0..1; total is the weighted sum used for ranking (SPEC §9). */
export interface ScoreBreakdown {
  major_fit: number;
  affordability: number;
  outcomes: number;
  admission_fit: number;
  preferences: number;
  total: number;
}

export type ClaimField =
  | "net_price"
  | "admission_rate"
  | "sat_range"
  | "act_range"
  | "completion_rate"
  | "program_median_earnings"
  | "program_median_debt"
  | "median_earnings_10yr"
  | "median_debt"
  | "undergrad_size"
  | "city_state";

export interface Claim {
  unitid: number;
  field: ClaimField;
  cip4: string | null;
  /** As shown to the student, e.g. "$14,200" or "62%". */
  value: string;
}

export interface VerifiedClaim extends Claim {
  verified: boolean;
  db_value: string | null;
}

/** What the web app renders for one school. */
export interface RecommendationOut {
  unitid: number;
  name: string;
  city: string;
  state: string;
  cip4: string | null;
  cip_title: string | null;
  rank: number;
  admission_band: AdmissionBand;
  band_confidence: BandConfidence;
  scores: ScoreBreakdown;
  /** Short prose, never numbers. */
  reasons: string[];
  claims: VerifiedClaim[];
  net_price_basis: NetPriceBasis;
}

export interface RecommendationSet {
  id: string;
  session_id: string;
  retrieval_mode: RetrievalMode;
  recommendations: RecommendationOut[];
  /** verified claims / all claims */
  groundedness: number;
  created_at: string;
}

// ---------------------------------------------------------------- API I/O

export interface SessionCreate {
  mode?: SessionMode;
}

export interface SessionOut {
  id: string;
  mode: SessionMode;
  created_at: string;
}

/** Body of POST /api/sessions/{id}/turns. Strict: no other keys. */
export interface TurnIn {
  text: string;
}

export interface TurnOut {
  idx: number;
  role: "user" | "assistant";
  text: string;
  interrupted: boolean;
  at: string;
}

export interface SessionState {
  session: SessionOut;
  profile: StudentProfile;
  turns: TurnOut[];
  ready: boolean;
  missing: string[];
}

export interface RecommendRequest {
  mode?: RetrievalMode;
  k?: number;
}

/** SSE events from POST /api/sessions/{id}/turns (`event:` name -> `data:` JSON). */
export type TurnEvent =
  | { type: "token"; text: string }
  | { type: "profile"; profile: StudentProfile }
  | { type: "ready"; ready: boolean; missing: string[] }
  | { type: "done"; turn_id: string; assistant_text: string }
  | { type: "error"; message: string };

// ------------------------------------------------------------- voice (WS)
// WS /api/sessions/{id}/voice — protocol in backend/app/voice/gateway.py.

export type VoiceServerState = "listening" | "thinking" | "speaking";

/** GET /api/voice/status */
export interface VoiceStatus {
  available: boolean;
  provider: string | null;
  barge_in: boolean;
}

/** Time-to-first-audio breakdown for one voice turn (ms; null = not measured). */
export interface VoiceTurnMetrics {
  turn: number;
  turn_id: string | null;
  stt_final_ms: number | null;
  llm_ttft_ms: number | null;
  first_sentence_ms: number | null;
  tts_first_chunk_ms: number | null;
  playback_ms: number | null;
  ttfa_total_ms: number | null;
  interrupted: boolean;
  audio: boolean;
}

/** JSON frames the server sends (binary frames are PCM16 audio for the last audio_start). */
export type VoiceServerEvent =
  | { type: "hello"; barge_in: boolean; input_sample_rate: number; output_sample_rate: number; provider: string }
  | { type: "state"; state: VoiceServerState }
  | { type: "transcript_interim"; text: string }
  | { type: "transcript_final"; text: string; turn: number }
  | { type: "assistant_text"; delta: string; turn: number }
  | { type: "profile"; profile: StudentProfile }
  | { type: "ready"; ready: boolean; missing: string[] }
  | { type: "audio_start"; turn: number; sentence: number; text: string; sample_rate: number }
  | { type: "audio_end"; turn: number; sentence: number }
  | { type: "done"; turn: number; turn_id: string | null; assistant_text: string; audio: boolean }
  | { type: "interrupted"; turn: number; turn_id: string | null; played_through: number; assistant_text: string }
  | ({ type: "metrics" } & VoiceTurnMetrics)
  | { type: "error"; code: string; message: string; fatal: boolean };

/** JSON frames the client sends (mic audio goes as binary PCM16 16 kHz mono). */
export type VoiceClientMessage =
  | { type: "speech_end"; t_ms: number; sent_ms: number }
  | { type: "playback_start"; turn: number; t_ms: number; sent_ms: number }
  | { type: "played"; turn: number; sentence: number }
  | { type: "interrupt"; turn: number; last_played: number; sent_ms: number }
  | { type: "stop" };
