import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import AuditLog from "./pages/AuditLog";
import Dashboard from "./pages/Dashboard";
import Elsets from "./pages/Elsets";
import ElsetDetail from "./pages/ElsetDetail";
import Login from "./pages/Login";
import Notifications from "./pages/Notifications";
import NotificationDetail from "./pages/NotificationDetail";
import Procedures from "./pages/Procedures";

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
            <Route path="/elsets" element={<Elsets />} />
            <Route path="/elsets/:id" element={<ElsetDetail />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/notifications/:id" element={<NotificationDetail />} />
            <Route path="/procedures" element={<Procedures />} />
            <Route path="/audit" element={<AuditLog />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
