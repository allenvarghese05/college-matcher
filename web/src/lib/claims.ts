import type { ClaimField, RecommendationOut, VerifiedClaim } from "@/lib/types";

export const CLAIM_LABEL: Record<ClaimField, string> = {
  net_price: "Net price at your income",
  admission_rate: "Admission rate",
  sat_range: "SAT, middle 50%",
  act_range: "ACT, middle 50%",
  completion_rate: "Graduation rate",
  program_median_earnings: "Median earnings, this major",
  program_median_debt: "Median debt, this major",
  median_earnings_10yr: "Median earnings, school-wide",
  median_debt: "Median debt, school-wide",
  undergrad_size: "Undergraduates",
  city_state: "Location",
};

/** Short mono labels for the card's three key numbers. */
const SHORT: Partial<Record<ClaimField, string>> = {
  net_price: "Net price / yr",
  program_median_earnings: "Earnings · major",
  median_earnings_10yr: "Earnings · school-wide",
  completion_rate: "Graduates",
};

/** Unverified claims come back with verified:false and are never shown (SPEC §8). */
export const visibleClaims = (r: RecommendationOut): VerifiedClaim[] => r.claims.filter((c) => c.verified);

export const claimValue = (r: RecommendationOut, field: ClaimField): string | null =>
  visibleClaims(r).find((c) => c.field === field)?.value ?? null;

/** Display location. city/state are DB display data, so they need no claim. */
export const place = (r: RecommendationOut): string =>
  claimValue(r, "city_state") ?? [r.city, r.state].filter(Boolean).join(", ");

export interface KeyNumber {
  field: ClaimField;
  label: string;
  value: string;
}

/** Net price, earnings (by major, else school-wide), graduation rate. */
export function keyNumbers(r: RecommendationOut): KeyNumber[] {
  const earningsField: ClaimField = claimValue(r, "program_median_earnings")
    ? "program_median_earnings"
    : "median_earnings_10yr";
  const fields: ClaimField[] = ["net_price", earningsField, "completion_rate"];
  return fields.flatMap((field) => {
    const value = claimValue(r, field);
    return value ? [{ field, label: SHORT[field] ?? CLAIM_LABEL[field], value }] : [];
  });
}

export const EARNINGS_CAVEAT = "Earnings cover federal-aid recipients; some programs are too small to report.";
