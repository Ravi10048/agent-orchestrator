import { Suspense, lazy } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { CommandPalette } from "@/components/CommandPalette";
import { Spinner } from "@/components/ui/feedback";
import { Toaster } from "@/components/ui/toaster";
import AgentsPage from "@/pages/Agents";
import ConversationsPage from "@/pages/Conversations";
import Dashboard from "@/pages/Dashboard";
import RunsPage from "@/pages/Runs";
import TemplatesPage from "@/pages/Templates";
import ToolsPage from "@/pages/Tools";
import WorkflowsPage from "@/pages/Workflows";

// code-split the heavy React Flow canvas — only loaded when the builder opens
const WorkflowBuilder = lazy(() => import("@/pages/WorkflowBuilder"));
// code-split the live monitor (pulls in recharts) — loaded the first time a run opens (?run=)
const RunDrawer = lazy(() => import("@/components/RunDrawer").then((m) => ({ default: m.RunDrawer })));
// code-split the run-graph trace view (React Flow) — full-screen execution replay on the canvas
const RunGraph = lazy(() => import("@/pages/RunGraph"));
// code-split the workflow chat playground (React Flow + live chat) — full-screen split view
const WorkflowChat = lazy(() => import("@/pages/WorkflowChat"));

export default function App() {
  return (
    <BrowserRouter>
      <Toaster />
      <CommandPalette />
      <Suspense fallback={null}>
        <RunDrawer />
      </Suspense>
      <Routes>
        {/* full-screen builder — outside the app shell for max canvas */}
        <Route
          path="/workflows/:id/build"
          element={
            <Suspense fallback={<div className="grid h-screen place-items-center"><Spinner className="h-6 w-6" /></div>}>
              <WorkflowBuilder />
            </Suspense>
          }
        />
        {/* full-screen run trace on the workflow graph */}
        <Route
          path="/runs/:id/graph"
          element={
            <Suspense fallback={<div className="grid h-screen place-items-center"><Spinner className="h-6 w-6" /></div>}>
              <RunGraph />
            </Suspense>
          }
        />
        {/* full-screen workflow chat playground — live graph + chat */}
        <Route
          path="/workflows/:id/chat"
          element={
            <Suspense fallback={<div className="grid h-screen place-items-center"><Spinner className="h-6 w-6" /></div>}>
              <WorkflowChat />
            </Suspense>
          }
        />
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/conversations" element={<ConversationsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
