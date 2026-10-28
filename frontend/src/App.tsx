import { useState } from "react";
import { MotionConfig } from "motion/react";
import { AppShell, ROUTES } from "./components/Shell";
import { JobDrawer } from "./components/JobDrawer";
import { ErrorNote, ToastProvider } from "./components/ui";
import { AppStateProvider, useApp } from "./lib/appState";
import { useHashRoute } from "./lib/hooks";
import { ThemeProvider } from "./lib/theme";
import Controller from "./pages/Controller";
import Experiments from "./pages/Experiments";
import Ledger from "./pages/Ledger";
import LiveMode from "./pages/LiveMode";
import Overview from "./pages/Overview";
import Workloads from "./pages/Workloads";

function Body() {
  const [route, navigate] = useHashRoute("overview");
  const [jobId, setJobId] = useState<string | null>(null);
  const { error, state } = useApp();
  const valid = ROUTES.some((r) => r.id === route) ? route : "overview";
  return (
    <>
      <AppShell route={valid} onNavigate={navigate}>
        <div className="mx-auto flex max-w-[1400px] flex-col gap-8 px-8 pb-24 lg:px-12">
          {error && state && <div className="pt-6"><ErrorNote message={`Lost contact with the backend: ${error}`} /></div>}
          {valid === "overview" && <Overview onOpenJob={setJobId} />}
          {valid === "queue" && <Workloads onOpenJob={setJobId} />}
          {valid === "scheduler" && <Controller onOpenJob={setJobId} />}
          {valid === "experiments" && <Experiments />}
          {valid === "history" && <Ledger onOpenJob={setJobId} />}
          {valid === "live" && <LiveMode />}
        </div>
      </AppShell>
      <JobDrawer jobId={jobId} onClose={() => setJobId(null)} />
    </>
  );
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <ThemeProvider>
        <ToastProvider>
          <AppStateProvider>
            <Body />
          </AppStateProvider>
        </ToastProvider>
      </ThemeProvider>
    </MotionConfig>
  );
}
