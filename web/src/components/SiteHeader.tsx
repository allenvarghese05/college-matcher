import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { USE_MOCKS } from "@/lib/api";
import { MonoLabel } from "@/components/MonoLabel";
import { ThemeToggle } from "@/components/ThemeToggle";

export function SiteHeader({ children }: { children?: ReactNode }) {
  return (
    <header className="relative z-10 mx-auto flex h-16 w-full max-w-6xl items-center justify-between px-6 md:px-8">
      <Link to="/" className="group inline-flex items-center gap-3 rounded-full" aria-label="College Matcher, home">
        <span
          aria-hidden
          className="size-4 rounded-full bg-[radial-gradient(circle_at_35%_30%,var(--orb-core),var(--lavender)_45%,var(--sky))] transition-transform duration-500 ease-calm group-hover:scale-110"
        />
        <span className="font-medium tracking-[-0.02em]">College Matcher</span>
      </Link>
      <div className="flex items-center gap-2">
        {children}
        {USE_MOCKS && (
          <MonoLabel className="hidden rounded-full border border-line px-2.5 py-1 sm:inline-block">Mock data</MonoLabel>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}
