import { ArrowUp } from "lucide-react";
import { forwardRef, useState, type FormEvent } from "react";
import { cn } from "@/lib/utils";

/** TurnIn.text max_length in schemas.py. */
const MAX = 4000;
/** Show the remaining-characters hint only near the limit. */
const HINT_AT = 3600;

interface ComposerProps {
  onSend: (text: string) => void;
  busy?: boolean;
  className?: string;
}

/** Text fallback for the counselor. Enter sends; the field stays usable while a reply streams. */
export const Composer = forwardRef<HTMLInputElement, ComposerProps>(({ onSend, busy = false, className }, ref) => {
  const [text, setText] = useState("");
  const canSend = text.trim().length > 0 && !busy;
  const left = MAX - text.length;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <form
      onSubmit={submit}
      className={cn(
        "frost flex h-14 items-center gap-2 rounded-full pl-6 pr-2 transition-shadow focus-within:shadow-[0_0_0_2px_var(--focus)]",
        className,
      )}
    >
      <label htmlFor="composer" className="sr-only">
        Message the counselor
      </label>
      <input
        ref={ref}
        id="composer"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Type instead…"
        autoComplete="off"
        maxLength={MAX}
        aria-describedby={text.length >= HINT_AT ? "composer-count" : undefined}
        className="h-full min-w-0 flex-1 bg-transparent text-body text-ink placeholder:text-ink-muted focus:outline-none focus-visible:outline-none"
      />
      {text.length >= HINT_AT && (
        <span id="composer-count" className="mono-label shrink-0 text-ink-muted">
          {left.toLocaleString()} left
        </span>
      )}
      <button
        type="submit"
        disabled={!canSend}
        aria-label="Send"
        className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-primary text-primary-ink transition-[opacity,transform] duration-200 active:scale-95 disabled:opacity-25"
      >
        <ArrowUp className="size-[18px]" aria-hidden />
      </button>
    </form>
  );
});
Composer.displayName = "Composer";
