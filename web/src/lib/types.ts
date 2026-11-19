/**
 * Hand-written mirror of the backend contracts in docs/SPEC.md §6
 * (backend/app/schemas.py).
 *
 * TEMPORARY: this file will be replaced by types generated from the FastAPI
 * OpenAPI schema. Keep names and shapes 1:1 with the Pydantic models so the
 * swap is mechanical. Anything marked "view" is a UI-facing extension the
 * backend still needs to agree to.
 */

// ---------- Profile ----------

export type EvidenceSource = "chat" | "voice" | "resume" | "quiz";

export interface Evidence {
  /** The student's exact words. */
  quote: string;
  turn_idx: number;
  source: EvidenceSource;
}

export interface Field<T> {
  value: T | null;
  /** 0..1, set by the extractor. */
  confidence: number;
  evidence: Evidence[];
}

export type IncomeBracket = "0-30k" | "30-48k" | "48-75k" | "75-110k" | "110k+";
export type SizePref = "small" | "medium" | "large" | "any";
export type SettingPref = "city" | "suburb" | "town" | "rural" | "any";
export type Priority = "cost" | "outcomes" | "prestige" | "location" | "fit";
export type RiasecCode = "R" | "I" | "A" | "S" | "E" | "C";

export interface Activity {
  name: string;
  kind: "club" | "sport" | "job" | "volunteering" | "leadership" | "project" | "other";
  role?: string | null;
}

export interface StudentProfile {
  // identity & location
  home_state: Field<string>;
  home_zip: Field<string>;
  // academics
  gpa: Field<number>;
  sat: Field<number>;
  act: Field<number>;
  // money
  income_bracket: Field<IncomeBracket>;
  budget_cap: Field<number>;
  // interests & direction
  interests: Field<string[]>;
  dream_without_money: Field<string>;
  intended_majors: Field<string[]>;
  riasec: Field<Partial<Record<RiasecCode, number>>>;
  strengths: Field<string[]>;
  favorite_subjects: Field<string[]>;
  activities: Field<Activity[]>;
  work_values: Field<string[]>;
  // fit preferences
  max_distance_miles: Field<number>;
  regions: Field<string[]>;
  size_pref: Field<SizePref>;
  setting_pref: Field<SettingPref>;
  priorities: Field<Priority[]>;
}

export type ProfileKey = keyof StudentProfile;

// ---------- Recommendations ----------

export type AdmissionBand = "safety" | "target" | "reach" | "unknown";

export type ClaimField =
  | "net_price"
  | "admission_rate"
  | "sat_range"
  | "completion_rate"
  | "program_median_earnings"
  | "program_median_debt"
  | "median_earnings_10yr"
  | "undergrad_size"
  | "city_state";

/** Every number shown to a student is a Claim. */
export interface Claim {
  unitid: number;
  field: ClaimField;
  cip4: string | null;
  /** As stated; the groundedness checker parses and compares. */
  value: string;
}

/** view: Claim after the groundedness check (CLAIM.verified in the DB). */
export interface CheckedClaim extends Claim {
  verified: boolean;
}

export interface Recommendation {
  unitid: number;
  cip4: string | null;
  admission_band: AdmissionBand;
  /** Short prose, never numbers. */
  reasons: string[];
  claims: CheckedClaim[];
}

/** SPEC §9 Stage C: each component 0..1. */
export interface ScoreBreakdown {
  major_fit: number;
  affordability: number;
  outcomes: number;
  admission_fit: number;
  preferences: number;
  /** Weighted total, 0..1. */
  total: number;
}

/**
 * view: what the results screen needs on top of `Recommendation`.
 * Names and titles are display data joined from INSTITUTION / CIP_CODE;
 * they are not claims, so they carry no numbers.
 */
export interface RecommendationView extends Recommendation {
  rank: number;
  institution: { unitid: number; name: string };
  major: { cip4: string; title: string } | null;
  score_breakdown: ScoreBreakdown;
}

export interface RecommendationSet {
  id: string;
  session_id: string;
  /** Data release the claims were checked against. */
  data_release: string;
  recommendations: RecommendationView[];
}

// ---------- Sessions & turns ----------

export type SessionMode = "text" | "voice";

export interface Session {
  id: string;
  mode: SessionMode;
  created_at: string;
}

export type Role = "student" | "counselor";

export interface Turn {
  idx: number;
  role: Role;
  text: string;
  source?: EvidenceSource;
  interrupted?: boolean;
}

/** Server-sent events from POST /sessions/{id}/turns (SPEC §8). */
export type TurnEvent =
  | { type: "token"; text: string }
  | { type: "profile"; profile: StudentProfile }
  | { type: "recommendations_available" }
  | { type: "done"; turn_idx: number };
