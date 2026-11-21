/**
 * MOCK DATA. A fictional Ohio student, matching the `maya-oh` persona in
 * docs/SPEC.md §10. Not a real person.
 */
import type { Evidence, ProfileField, ProfileKey, StudentProfile } from "@/lib/types";

const empty = <T,>(): ProfileField<T> => ({ value: null, confidence: 0, evidence: [] });

export function emptyProfile(): StudentProfile {
  return {
    home_state: empty(),
    home_zip: empty(),
    gpa: empty(),
    sat: empty(),
    act: empty(),
    income_bracket: empty(),
    budget_cap: empty(),
    interests: empty(),
    dream_without_money: empty(),
    intended_majors: empty(),
    riasec: empty(),
    strengths: empty(),
    favorite_subjects: empty(),
    activities: empty(),
    work_values: empty(),
    max_distance_miles: empty(),
    regions: empty(),
    size_pref: empty(),
    setting_pref: empty(),
    priorities: empty(),
  };
}

/** A partial update the mock extractor applies after a student turn. */
export type ProfilePatch = {
  [K in ProfileKey]?: { value: StudentProfile[K]["value"]; confidence: number; quote: string };
};

export interface ScriptStep {
  /** What the student says (used verbatim by the mock voice path). */
  student: string;
  /** The counselor's reply, streamed token by token. */
  counselor: string;
  patch: ProfilePatch;
}

export const GREETING =
  "Hi. I'm here to help you think through college, at whatever pace feels right. What's on your mind about it right now?";

export const SCRIPT: ScriptStep[] = [
  {
    student: "Honestly I don't really know where to start. Everyone keeps asking what I want to major in.",
    counselor:
      "That's a lot of people asking the same hard question. Let's come at it sideways. If money weren't involved and you weren't getting paid, what would you happily do for the rest of your life?",
    patch: {},
  },
  {
    student:
      "Probably design stuff. Like things people actually use every day. I draw a lot, and I fix bikes for my neighbors.",
    counselor:
      "Drawing and fixing bikes is a lovely pairing. One is imagining things, the other is knowing how they really work. Which classes feel closest to that?",
    patch: {
      dream_without_money: {
        value: "Design things people use every day",
        confidence: 0.86,
        quote: "design stuff. Like things people actually use every day",
      },
      interests: { value: ["Drawing", "Fixing bikes"], confidence: 0.82, quote: "I draw a lot, and I fix bikes" },
      activities: {
        value: [{ name: "Bike repair for neighbors", role: null, years: 2, hours_per_week: 4 }],
        confidence: 0.74,
        quote: "I fix bikes for my neighbors",
      },
    },
  },
  {
    student: "Physics and art, I guess. I like figuring out how things are built.",
    counselor:
      "That points toward a few majors I'd like to show you. To estimate your chances, it helps to know your GPA and any SAT or ACT score. Totally optional.",
    patch: {
      favorite_subjects: { value: ["Physics", "Art"], confidence: 0.8, quote: "Physics and art, I guess" },
      interests: {
        value: ["Drawing", "Fixing bikes", "How things are built"],
        confidence: 0.85,
        quote: "I like figuring out how things are built",
      },
    },
  },
  {
    student: "3.6 unweighted, and I got a 1310 on the SAT.",
    counselor: "Thanks, that's useful. Where do you live, and how far from home would you be okay going?",
    patch: {
      gpa: { value: 3.6, confidence: 0.95, quote: "3.6 unweighted" },
      sat: { value: 1310, confidence: 0.95, quote: "I got a 1310 on the SAT" },
    },
  },
  {
    student: "Ohio, near Columbus. Not more than like five hours away.",
    counselor:
      "Got it. Cost matters for almost everyone. Roughly what does your family earn in a year? The federal data groups it into five ranges, so a ballpark is fine.",
    patch: {
      home_state: { value: "OH", confidence: 0.97, quote: "Ohio, near Columbus" },
      max_distance_miles: { value: 300, confidence: 0.7, quote: "Not more than like five hours away" },
    },
  },
  {
    student: "My parents make somewhere around sixty thousand.",
    counselor:
      "Thank you for sharing that. Last one for now. When you picture choosing a school, what matters most: the cost, what graduates earn, the name, the location, or how it feels?",
    patch: {
      income_bracket: { value: "48-75k", confidence: 0.84, quote: "somewhere around sixty thousand" },
    },
  },
  {
    student: "Cost for sure. And that I can get a good job after.",
    counselor:
      "That gives me a clear picture. I have enough to show you some matches whenever you're ready, and we can keep refining after.",
    patch: {
      priorities: { value: ["cost", "outcomes"], confidence: 0.88, quote: "Cost for sure. And that I can get a good job after" },
    },
  },
];

export const FALLBACK_REPLY =
  "I've noted that. Whenever you're ready, open your matches, and we can keep adjusting from there.";

export function applyPatch(
  profile: StudentProfile,
  patch: ProfilePatch,
  turnIdx: number,
  source: Evidence["source"],
): StudentProfile {
  const next: StudentProfile = { ...profile };
  for (const key of Object.keys(patch) as ProfileKey[]) {
    const update = patch[key];
    if (!update) continue;
    const prev = profile[key] as ProfileField<unknown>;
    (next as Record<ProfileKey, ProfileField<unknown>>)[key] = {
      value: update.value,
      confidence: update.confidence,
      evidence: [...prev.evidence, { quote: update.quote, turn_idx: turnIdx, source }],
    };
  }
  return next;
}

/** The fully-filled profile after the whole script. */
export const MOCK_PROFILE: StudentProfile = SCRIPT.reduce(
  (p, step, i) => applyPatch(p, step.patch, i * 2 + 1, "chat"),
  emptyProfile(),
);
