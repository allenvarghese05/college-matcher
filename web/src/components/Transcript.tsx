import { useEffect, useRef } from "react";
import type { TurnOut } from "@/lib/types";
import { useReducedMotion } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { MonoLabel } from "@/components/MonoLabel";

interface TranscriptProps {
  turns: TurnOut[];
  /** Counselor reply currently streaming in. */
  streaming?: string | null;
  /** Student words heard so far while listening. */
  interim?: string | null;
  className?: string;
}

export function Transcript({ turns, streaming, interim, className }: TranscriptProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "end" });
  }, [turns.length, streaming, interim, reduced]);

  return (
    <div className={cn("flex flex-col gap-8", className)}>
      <ol role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation" className="flex flex-col gap-8">
        {turns.map((t) => (
          <li key={t.idx} className="rise">
            <Line role={t.role} text={t.text} />
          </li>
        ))}
      </ol>
      {interim && (
        <div aria-hidden>
          <Line role="user" text={interim} pending />
        </div>
      )}
      {streaming !== null && streaming !== undefined && (
        <div aria-hidden>
          <Line role="assistant" text={streaming} pending />
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}

function Line({ role, text, pending = false }: { role: TurnOut["role"]; text: string; pending?: boolean }) {
  if (role === "user") {
    return (
      <div className="ml-auto flex max-w-[85%] flex-col items-end gap-2">
        <MonoLabel>You</MonoLabel>
        <p
          className={cn(
            "rounded-md rounded-tr-sm bg-surface-sunken px-4 py-3 text-ink",
            pending && "text-ink-muted",
          )}
        >
          {text}
          {pending && <span className="caret" />}
        </p>
      </div>
    );
  }
  return (
    <div className="flex max-w-[92%] flex-col gap-2">
      <MonoLabel>Counselor</MonoLabel>
      <p className={cn("text-ink text-pretty", pending && "caret")}>{text}</p>
    </div>
  );
}
