import { ReactNode } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

interface Props {
  children?: ReactNode;
}

export default function ProtectedRoute({ children }: Props) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children ?? <Outlet />}</>;
}
