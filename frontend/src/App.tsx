import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Elsets from "./pages/Elsets";
import Login from "./pages/Login";
import Notsos from "./pages/Notsos";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/elsets" element={<Elsets />} />
            <Route path="/notsos" element={<Notsos />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}