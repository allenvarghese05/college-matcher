import { Link } from "react-router-dom";
import { MonoLabel } from "@/components/MonoLabel";
import { SiteHeader } from "@/components/SiteHeader";
import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <div className="min-h-dvh">
      <SiteHeader />
      <main id="main" className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-6 py-32 md:px-8">
        <MonoLabel>404</MonoLabel>
        <h1 className="text-title font-medium">There's nothing here.</h1>
        <Button asChild variant="secondary">
          <Link to="/">Back to the start</Link>
        </Button>
      </main>
    </div>
  );
}
