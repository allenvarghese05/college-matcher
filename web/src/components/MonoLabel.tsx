import type { ElementType, ReactNode } from "react";
import { cn } from "@/lib/utils";

interface MonoLabelProps {
  children: ReactNode;
  /** Optional value rendered after a middle dot: "NET PRICE · $14,200". */
  value?: ReactNode;
  as?: ElementType;
  className?: string;
  muted?: boolean;
  id?: string;
}

/** Small uppercase letter-spaced monospace label for data and eyebrows. */
export function MonoLabel({ children, value, as: Tag = "span", className, muted = true, id }: MonoLabelProps) {
  return (
    <Tag id={id} className={cn("mono-label", muted ? "text-ink-muted" : "text-ink", className)}>
      {children}
      {value !== undefined && (
        <>
          <span aria-hidden className="px-[0.6em] text-ink-faint">
            ·
          </span>
          <span className="text-ink">{value}</span>
        </>
      )}
    </Tag>
  );
}
