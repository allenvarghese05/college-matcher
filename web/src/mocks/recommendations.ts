/**
 * MOCK DATA. School names are real so the layout can be judged honestly,
 * but every number, ID and score below is invented for UI development.
 * Nothing here is College Scorecard data. The UI shows a "Mock data" badge
 * whenever these are in use.
 */
import type {
  AdmissionBand,
  CheckedClaim,
  ClaimField,
  RecommendationSet,
  RecommendationView,
  ScoreBreakdown,
} from "@/lib/types";

interface Seed {
  unitid: number;
  name: string;
  cityState: string;
  major: { cip4: string; title: string };
  band: AdmissionBand;
  netPrice: string;
  /** By-major earnings, or null when the program is too small to report. */
  programEarnings: string | null;
  schoolEarnings: string;
  completion: string;
  admission: string;
  sat: string;
  debt: string | null;
  size: string;
  scores: Omit<ScoreBreakdown, "total">;
  reasons: string[];
}

const SEEDS: Seed[] = [
  {
    unitid: 900101,
    name: "The Ohio State University",
    cityState: "Columbus, OH",
    major: { cip4: "14.19", title: "Mechanical Engineering" },
    band: "target",
    netPrice: "$17,400",
    programEarnings: "$78,900",
    schoolEarnings: "$61,300",
    completion: "88%",
    admission: "53%",
    sat: "1260–1440",
    debt: "$23,000",
    size: "47,100",
    scores: { major_fit: 0.91, affordability: 0.78, outcomes: 0.86, admission_fit: 0.72, preferences: 0.95 },
    reasons: [
      "A large, hands-on engineering college close to home, with design studios open to first-years.",
      "In-state pricing keeps it within reach for your family's income range.",
    ],
  },
  {
    unitid: 900102,
    name: "University of Cincinnati",
    cityState: "Cincinnati, OH",
    major: { cip4: "50.04", title: "Industrial Design" },
    band: "target",
    netPrice: "$16,800",
    programEarnings: "$58,200",
    schoolEarnings: "$54,700",
    completion: "73%",
    admission: "86%",
    sat: "1170–1370",
    debt: "$24,500",
    size: "30,400",
    scores: { major_fit: 0.96, affordability: 0.8, outcomes: 0.71, admission_fit: 0.8, preferences: 0.88 },
    reasons: [
      "Its industrial design program is built around paid co-op terms, so you design real products before graduating.",
      "Closest match to wanting to design things people use every day.",
    ],
  },
  {
    unitid: 900103,
    name: "Ohio University",
    cityState: "Athens, OH",
    major: { cip4: "14.19", title: "Mechanical Engineering" },
    band: "safety",
    netPrice: "$15,600",
    programEarnings: "$69,800",
    schoolEarnings: "$48,900",
    completion: "66%",
    admission: "88%",
    sat: "1080–1270",
    debt: "$24,900",
    size: "17,900",
    scores: { major_fit: 0.85, affordability: 0.84, outcomes: 0.74, admission_fit: 0.93, preferences: 0.79 },
    reasons: [
      "A smaller college town campus with a practical engineering program and lots of shop access.",
      "Your scores sit comfortably above its typical admitted range.",
    ],
  },
  {
    unitid: 900104,
    name: "Miami University",
    cityState: "Oxford, OH",
    major: { cip4: "14.19", title: "Mechanical Engineering" },
    band: "target",
    netPrice: "$21,900",
    programEarnings: "$74,300",
    schoolEarnings: "$66,200",
    completion: "83%",
    admission: "80%",
    sat: "1200–1380",
    debt: "$27,000",
    size: "17,200",
    scores: { major_fit: 0.84, affordability: 0.64, outcomes: 0.83, admission_fit: 0.78, preferences: 0.82 },
    reasons: [
      "Small engineering classes on a residential campus, with strong graduation outcomes.",
      "Costs more than the in-state publics, but graduates in this major do well.",
    ],
  },
  {
    unitid: 900105,
    name: "Kent State University",
    cityState: "Kent, OH",
    major: { cip4: "50.04", title: "Industrial Design" },
    band: "safety",
    netPrice: "$14,200",
    programEarnings: null,
    schoolEarnings: "$47,600",
    completion: "67%",
    admission: "87%",
    sat: "1040–1250",
    debt: "$23,500",
    size: "21,300",
    scores: { major_fit: 0.9, affordability: 0.88, outcomes: 0.58, admission_fit: 0.94, preferences: 0.8 },
    reasons: [
      "One of the most affordable options here, with a design school that mixes drawing and making.",
      "The design program is too small for federal earnings data, so outcomes use the school-wide figure.",
    ],
  },
  {
    unitid: 900106,
    name: "University of Dayton",
    cityState: "Dayton, OH",
    major: { cip4: "14.19", title: "Mechanical Engineering" },
    band: "target",
    netPrice: "$24,300",
    programEarnings: "$76,500",
    schoolEarnings: "$63,900",
    completion: "81%",
    admission: "77%",
    sat: "1150–1330",
    debt: "$26,000",
    size: "8,600",
    scores: { major_fit: 0.83, affordability: 0.58, outcomes: 0.84, admission_fit: 0.82, preferences: 0.84 },
    reasons: [
      "A private university with a close-knit engineering school and an innovation centre for student projects.",
      "Generous aid narrows the gap with public options at your income.",
    ],
  },
  {
    unitid: 900107,
    name: "Bowling Green State University",
    cityState: "Bowling Green, OH",
    major: { cip4: "15.08", title: "Mechanical Engineering Technology" },
    band: "safety",
    netPrice: "$13,900",
    programEarnings: "$61,200",
    schoolEarnings: "$46,800",
    completion: "65%",
    admission: "79%",
    sat: "1010–1220",
    debt: "$25,400",
    size: "14,700",
    scores: { major_fit: 0.78, affordability: 0.9, outcomes: 0.69, admission_fit: 0.95, preferences: 0.74 },
    reasons: [
      "An applied program for people who like fixing and building more than theory.",
      "Lowest price on this list for your income range.",
    ],
  },
  {
    unitid: 900108,
    name: "Case Western Reserve University",
    cityState: "Cleveland, OH",
    major: { cip4: "14.19", title: "Mechanical Engineering" },
    band: "reach",
    netPrice: "$22,100",
    programEarnings: "$84,700",
    schoolEarnings: "$80,200",
    completion: "87%",
    admission: "29%",
    sat: "1390–1530",
    debt: "$22,000",
    size: "6,200",
    scores: { major_fit: 0.87, affordability: 0.66, outcomes: 0.93, admission_fit: 0.41, preferences: 0.86 },
    reasons: [
      "A research university with a large maker space open to every undergraduate.",
      "A stretch on scores, but need-based aid could make it surprisingly affordable.",
    ],
  },
  {
    unitid: 900109,
    name: "Purdue University",
    cityState: "West Lafayette, IN",
    major: { cip4: "14.19", title: "Mechanical Engineering" },
    band: "reach",
    netPrice: "$24,800",
    programEarnings: "$80,100",
    schoolEarnings: "$72,400",
    completion: "84%",
    admission: "50%",
    sat: "1220–1470",
    debt: "$24,000",
    size: "39,200",
    scores: { major_fit: 0.89, affordability: 0.55, outcomes: 0.9, admission_fit: 0.48, preferences: 0.7 },
    reasons: [
      "One of the strongest mechanical engineering programs in the region, just over the state line.",
      "Admission to engineering is competitive, and out-of-state pricing applies.",
    ],
  },
  {
    unitid: 900110,
    name: "Carnegie Mellon University",
    cityState: "Pittsburgh, PA",
    major: { cip4: "50.04", title: "Industrial Design" },
    band: "reach",
    netPrice: "$28,600",
    programEarnings: null,
    schoolEarnings: "$98,400",
    completion: "93%",
    admission: "11%",
    sat: "1500–1560",
    debt: "$21,500",
    size: "7,500",
    scores: { major_fit: 0.95, affordability: 0.46, outcomes: 0.82, admission_fit: 0.18, preferences: 0.72 },
    reasons: [
      "A design school where drawing, engineering and research sit in the same building.",
      "Very selective, so treat it as a long shot worth one application.",
    ],
  },
];

const WEIGHTS: Record<keyof Omit<ScoreBreakdown, "total">, number> = {
  major_fit: 0.3,
  affordability: 0.25,
  outcomes: 0.2,
  admission_fit: 0.15,
  preferences: 0.1,
};

function total(s: Omit<ScoreBreakdown, "total">): number {
  const keys = Object.keys(WEIGHTS) as (keyof typeof WEIGHTS)[];
  return Math.round(keys.reduce((acc, k) => acc + s[k] * WEIGHTS[k], 0) * 100) / 100;
}

function toView(seed: Seed, index: number): RecommendationView {
  const c = (field: ClaimField, value: string, withMajor = false): CheckedClaim => ({
    unitid: seed.unitid,
    field,
    cip4: withMajor ? seed.major.cip4 : null,
    value,
    verified: true,
  });

  const claims: CheckedClaim[] = [
    c("city_state", seed.cityState),
    c("net_price", seed.netPrice),
    seed.programEarnings
      ? c("program_median_earnings", seed.programEarnings, true)
      : c("median_earnings_10yr", seed.schoolEarnings),
    c("completion_rate", seed.completion),
    c("admission_rate", seed.admission),
    c("sat_range", seed.sat),
    c("undergrad_size", seed.size),
  ];
  if (seed.debt) claims.push(c("program_median_debt", seed.debt, true));

  return {
    rank: index + 1,
    unitid: seed.unitid,
    cip4: seed.major.cip4,
    institution: { unitid: seed.unitid, name: seed.name },
    major: seed.major,
    admission_band: seed.band,
    reasons: seed.reasons,
    claims,
    score_breakdown: { ...seed.scores, total: total(seed.scores) },
  };
}

export const MOCK_RECOMMENDATIONS: RecommendationSet = {
  id: "mock-set-0001",
  session_id: "mock-session",
  data_release: "College Scorecard, 2026 release",
  recommendations: SEEDS.map(toView),
};
