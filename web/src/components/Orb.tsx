import { useEffect, useRef, type CSSProperties } from "react";
import { useReducedMotion } from "@/lib/hooks";
import { cn } from "@/lib/utils";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

interface OrbProps {
  state: OrbState;
  size?: number;
  /**
   * Live audio level 0..1 (mic RMS while listening, TTS output while speaking).
   * When omitted, a gentle synthetic level is used so the mock feels alive.
   */
  getLevel?: () => number;
  className?: string;
}

/**
 * The counselor's voice orb. Decorative (aria-hidden): the surrounding UI
 * carries the state in text. Animation is CSS; this component only writes
 * the --level custom property on animation frames, without re-rendering.
 */
export function Orb({ state, size = 220, getLevel, className }: OrbProps) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const live = (state === "listening" || state === "speaking") && !reduced;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (!live) {
      el.style.setProperty("--level", "0");
      return;
    }
    let raf = 0;
    let smoothed = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = (now - start) / 1000;
      const target = getLevel
        ? getLevel()
        : state === "speaking"
          ? // syllable-ish rhythm
            0.45 + 0.35 * Math.sin(t * 9.1) * Math.sin(t * 2.3) + 0.2 * Math.sin(t * 17.3)
          : // breathing room noise while the student talks
            0.35 + 0.3 * Math.sin(t * 5.7) * Math.sin(t * 1.3) + 0.15 * Math.sin(t * 13.1);
      smoothed += (Math.max(0, Math.min(1, target)) - smoothed) * 0.18;
      el.style.setProperty("--level", smoothed.toFixed(3));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [live, state, getLevel]);

  return (
    <div
      ref={ref}
      aria-hidden
      data-state={state}
      className={cn("orb", className)}
      style={{ "--size": `${size}px` } as CSSProperties}
    >
      <div className="orb-breath">
        <div className="orb-halo" />
        <div className="orb-ripple" />
        <div className="orb-ripple" />
        <div className="orb-body">
          <div className="orb-swirl" />
          <div className="orb-sheen" />
        </div>
      </div>
    </div>
  );
}
