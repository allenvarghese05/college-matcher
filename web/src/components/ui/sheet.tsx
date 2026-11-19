import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { forwardRef, type ComponentPropsWithoutRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;
export const SheetClose = Dialog.Close;
export const SheetTitle = Dialog.Title;
export const SheetDescription = Dialog.Description;

interface SheetContentProps extends ComponentPropsWithoutRef<typeof Dialog.Content> {
  side?: "right" | "bottom";
  children: ReactNode;
  closeLabel?: string;
}

/** Keyboard-usable side sheet (Radix Dialog: focus trap, Esc to close, focus return). */
export const SheetContent = forwardRef<HTMLDivElement, SheetContentProps>(
  ({ side = "right", className, children, closeLabel = "Close", ...props }, ref) => (
    <Dialog.Portal>
      <Dialog.Overlay className="sheet-overlay fixed inset-0 z-40 bg-[var(--overlay)]" />
      <Dialog.Content
        ref={ref}
        data-side={side}
        className={cn(
          "sheet-content fixed z-50 flex flex-col bg-canvas text-ink shadow-[var(--shadow-soft)] outline-none",
          side === "right" &&
            "inset-y-0 right-0 w-full max-w-[560px] border-l border-line sm:inset-y-3 sm:right-3 sm:rounded-lg sm:border",
          side === "bottom" && "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-lg border-t border-line",
          className,
        )}
        {...props}
      >
        {children}
        <Dialog.Close
          className="absolute right-4 top-4 inline-flex size-10 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
          aria-label={closeLabel}
        >
          <X className="size-[18px]" aria-hidden />
        </Dialog.Close>
      </Dialog.Content>
    </Dialog.Portal>
  ),
);
SheetContent.displayName = "SheetContent";
