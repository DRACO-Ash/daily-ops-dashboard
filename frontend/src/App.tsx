import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import AuditLog from "./pages/AuditLog";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Maneuvers from "./pages/Maneuvers";
import Mattermost from "./pages/Mattermost";
import Notifications from "./pages/Notifications";
import NotificationDetail from "./pages/NotificationDetail";
import Procedures from "./pages/Procedures";
import ShiftLog from "./pages/ShiftLog";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<Dashboard />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/notifications/:id" element={<NotificationDetail />} />
            <Route path="/maneuvers" element={<Maneuvers />} />
            <Route path="/comms" element={<Mattermost />} />
            <Route path="/procedures" element={<Procedures />} />
            <Route path="/shift-log" element={<ShiftLog />} />
            <Route path="/audit" element={<AuditLog />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
