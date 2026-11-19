import { BrowserRouter, Route, Routes } from "react-router-dom";
import { SessionProvider } from "@/lib/session";
import { Landing } from "@/routes/Landing";
import { NotFound } from "@/routes/NotFound";
import { Quiz } from "@/routes/Quiz";
import { Results } from "@/routes/Results";
import { Talk } from "@/routes/Talk";

export function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-ink"
        >
          Skip to content
        </a>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/talk" element={<Talk />} />
          <Route path="/quiz" element={<Quiz />} />
          <Route path="/results" element={<Results />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
