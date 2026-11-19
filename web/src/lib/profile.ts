import type { Activity, IncomeBracket, ProfileField, ProfileKey, Riasec, StudentProfile } from "@/lib/types";

/** Readiness rule from SPEC §8 (StudentProfile.READY_MIN_CONFIDENCE). */
export const READY_CONFIDENCE = 0.6;

export const known = (f: ProfileField<unknown>): boolean =>
  f.value !== null &&
  f.value !== "" &&
  f.confidence >= READY_CONFIDENCE &&
  (!Array.isArray(f.value) || f.value.length > 0);

/** Mirrors StudentProfile.missing_for_recommendation() in schemas.py. */
export function missingForRecommendation(p: StudentProfile): string[] {
  const missing: string[] = [];
  if (!known(p.home_state)) missing.push("home_state");
  if (!known(p.income_bracket)) missing.push("income_bracket");
  if (!(known(p.interests) || known(p.intended_majors))) missing.push("interests");
  return missing;
}

export const isReady = (p: StudentProfile): boolean => missingForRecommendation(p).length === 0;

/** Plain words for the server's `missing` keys. */
export const MISSING_LABEL: Record<string, string> = {
  home_state: "home state",
  income_bracket: "family income",
  interests: "interests",
};

/** Fields the side panel shows, in the order the counselor tends to learn them. */
export const PANEL_FIELDS: { key: ProfileKey; label: string }[] = [
  { key: "dream_without_money", label: "If money weren't involved" },
  { key: "interests", label: "Interests" },
  { key: "favorite_subjects", label: "Favourite subjects" },
  { key: "activities", label: "Activities" },
  { key: "intended_majors", label: "Majors in mind" },
  { key: "gpa", label: "GPA" },
  { key: "sat", label: "SAT" },
  { key: "act", label: "ACT" },
  { key: "home_state", label: "Home state" },
  { key: "max_distance_miles", label: "Distance from home" },
  { key: "income_bracket", label: "Family income" },
  { key: "budget_cap", label: "Yearly budget" },
  { key: "size_pref", label: "School size" },
  { key: "setting_pref", label: "Setting" },
  { key: "priorities", label: "What matters most" },
];

/** Shown as placeholders even before they are filled, so the student sees what's useful. */
export const CORE_FIELDS: ProfileKey[] = [
  "dream_without_money",
  "interests",
  "gpa",
  "home_state",
  "income_bracket",
  "priorities",
];

const INCOME: Record<IncomeBracket, string> = {
  "0-30k": "Under $30k",
  "30-48k": "$30k–48k",
  "48-75k": "$48k–75k",
  "75-110k": "$75k–110k",
  "110k+": "Over $110k",
};

const STATES: Record<string, string> = {
  OH: "Ohio",
  IN: "Indiana",
  PA: "Pennsylvania",
  MI: "Michigan",
  KY: "Kentucky",
  WV: "West Virginia",
  NY: "New York",
  CA: "California",
  TX: "Texas",
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function formatField(key: ProfileKey, f: ProfileField<unknown>): string | null {
  const v = f.value;
  if (v === null || v === undefined) return null;
  if (Array.isArray(v) && v.length === 0) return null;
  switch (key) {
    case "income_bracket":
      return INCOME[v as IncomeBracket];
    case "home_state":
      return STATES[v as string] ?? (v as string);
    case "max_distance_miles":
      return `Within ${(v as number).toLocaleString()} mi`;
    case "budget_cap":
      return `$${(v as number).toLocaleString()} / yr`;
    case "gpa":
      return (v as number).toFixed(2).replace(/0$/, "");
    case "activities":
      return (v as Activity[]).map((a) => a.name).join(", ");
    case "priorities":
      return (v as string[]).map(cap).join(", ");
    case "riasec": {
      const r = v as Riasec;
      return (Object.keys(r) as (keyof Riasec)[])
        .sort((a, b) => r[b] - r[a])
        .slice(0, 3)
        .join("");
    }
    case "work_values":
      return (v as string[]).map((w) => cap(w.replace(/_/g, " "))).join(", ");
    default:
      if (Array.isArray(v)) return v.join(", ");
      return typeof v === "string" ? cap(v) : String(v);
  }
}

export function filledCount(p: StudentProfile): number {
  return PANEL_FIELDS.filter(({ key }) => formatField(key, p[key]) !== null).length;
}
