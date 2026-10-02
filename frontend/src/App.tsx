import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import { CLINICAL, homeFor, RESEARCH, useAuth } from "./lib/auth";
import type { Role } from "./lib/types";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import NewRecording from "./pages/NewRecording";
import { PatientDetail, PatientList } from "./pages/Patients";
import RecordingDetail from "./pages/RecordingDetail";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";

// Charts (recharts) only load for research users.
const ResearchLab = lazy(() => import("./pages/ResearchLab"));
const EvaluationDetail = lazy(() => import("./pages/ResearchLab").then((m) => ({ default: m.EvaluationDetail })));

function Guard({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return <>{children}</>;
}

export default function App() {
  const { user, loading } = useAuth();
  if (loading) return <Loading />;
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Guard>
            <Layout />
          </Guard>
        }
      >
        <Route index element={user?.role === "researcher" ? <Navigate to="/research" replace /> : <Guard roles={CLINICAL}><Dashboard /></Guard>} />
        <Route path="record" element={<Guard roles={CLINICAL}><NewRecording /></Guard>} />
        <Route path="patients" element={<Guard roles={CLINICAL}><PatientList /></Guard>} />
        <Route path="patients/:id" element={<Guard roles={CLINICAL}><PatientDetail /></Guard>} />
        <Route path="recordings/:id" element={<Guard roles={CLINICAL}><RecordingDetail /></Guard>} />
        <Route path="reports" element={<Guard roles={CLINICAL}><Reports /></Guard>} />
        <Route path="research" element={<Guard roles={RESEARCH}><Suspense fallback={<Loading />}><ResearchLab /></Suspense></Guard>} />
        <Route path="research/evaluations/:id" element={<Guard roles={RESEARCH}><Suspense fallback={<Loading />}><EvaluationDetail /></Suspense></Guard>} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
