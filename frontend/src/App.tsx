import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import AuditLog from "./pages/AuditLog";
import Dashboard from "./pages/Dashboard";
import Elsets from "./pages/Elsets";
import ElsetDetail from "./pages/ElsetDetail";
import Login from "./pages/Login";
import Notsos from "./pages/Notsos";
import NotsoDetail from "./pages/NotsoDetail";

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
            <Route path="/notsos" element={<Notsos />} />
            <Route path="/notsos/:id" element={<NotsoDetail />} />
            <Route path="/audit" element={<AuditLog />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
