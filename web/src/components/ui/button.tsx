import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full text-body font-medium tracking-[-0.01em] transition-[background-color,color,opacity,transform,border-color] duration-200 ease-calm active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40 [&_svg]:size-[18px] [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        /** Ink pill in light, cream pill in dark. */
        primary: "bg-primary text-primary-ink hover:opacity-90",
        /** Always cream: for use on dark or atmospheric backgrounds. */
        cream: "bg-cream text-[var(--cream-ink)] hover:opacity-90",
        secondary: "border border-line-strong bg-transparent text-ink hover:bg-surface",
        ghost: "text-ink-muted hover:bg-surface hover:text-ink",
      },
      size: {
        md: "h-10 px-5",
        lg: "h-12 px-7",
        icon: "size-10",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        {...(asChild ? {} : { type: type ?? "button" })}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

// eslint-disable-next-line react-refresh/only-export-components
export { buttonVariants };
