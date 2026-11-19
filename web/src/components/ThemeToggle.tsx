import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/hooks";

export function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={`Switch to ${next} theme`}
      className="inline-flex size-10 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-surface hover:text-ink"
    >
      {theme === "dark" ? <Sun className="size-[18px]" aria-hidden /> : <Moon className="size-[18px]" aria-hidden />}
    </button>
  );
}
