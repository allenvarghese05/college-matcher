import type { ClaimField, NetPriceBasis, RecommendationOut, VerifiedClaim } from "@/lib/types";

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

/** Short qualifier shown next to a net price (none for private schools). */
export const PRICE_BASIS_LABEL: Record<NetPriceBasis, string | null> = {
  in_state: "in-state",
  est_out_of_state: "est. out-of-state",
  private: null,
  unknown: "price not reported",
};

/** One plain sentence on where the net price comes from. */
export const PRICE_BASIS_NOTE: Record<NetPriceBasis, string> = {
  in_state: "This is the Scorecard's net price for families at your income, at in-state tuition.",
  est_out_of_state:
    "Estimated: the Scorecard's net price for your income assumes in-state tuition, so we added this school's extra out-of-state tuition and fees.",
  private: "This is the Scorecard's net price for families at your income; private schools charge the same in every state.",
  unknown: "This school doesn't report a net price we can use for your situation, so check its net price calculator.",
};

export interface KeyNumber {
  field: ClaimField;
  label: string;
  value: string;
  /** e.g. "est. out-of-state" under the net price */
  note?: string;
}

/** Net price, earnings (by major, else school-wide), graduation rate. */
export function keyNumbers(r: RecommendationOut): KeyNumber[] {
  const earningsField: ClaimField = claimValue(r, "program_median_earnings")
    ? "program_median_earnings"
    : "median_earnings_10yr";
  const fields: ClaimField[] = ["net_price", earningsField, "completion_rate"];
  return fields.flatMap((field): KeyNumber[] => {
    const label = SHORT[field] ?? CLAIM_LABEL[field];
    const value = claimValue(r, field);
    if (field === "net_price") {
      const basis = r.net_price_basis ?? "unknown";
      if (value) return [{ field, label, value, note: PRICE_BASIS_LABEL[basis] ?? undefined }];
      if (basis === "unknown") return [{ field, label, value: "—", note: PRICE_BASIS_LABEL.unknown ?? undefined }];
      return [];
    }
    return value ? [{ field, label, value }] : [];
  });
}

export const EARNINGS_CAVEAT = "Earnings cover federal-aid recipients; some programs are too small to report.";
