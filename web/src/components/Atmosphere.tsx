/** Soft lavender-to-sky wash behind a screen. Decorative; fixed; never intercepts input. */
export function Atmosphere({ intensity = "full" }: { intensity?: "full" | "faint" }) {
  return <div aria-hidden className="atmosphere" data-intensity={intensity} />;
}
