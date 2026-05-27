import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard" },
  { to: "/elsets", label: "Element sets" },
];

export default function Layout() {
  const { logout } = useAuth();
  const { pathname } = useLocation();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-title">Daily Operations Dashboard</div>
        <button type="button" className="logout-btn" onClick={logout}>
          Sign out
        </button>
      </header>
      <div className="app-body">
        <nav className="app-nav">
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={pathname === item.to ? "nav-link active" : "nav-link"}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
