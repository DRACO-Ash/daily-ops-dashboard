import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { EventTimersProvider } from "../context/EventTimersContext";
import TimerBanner from "./TimerBanner";
import type { UserRole } from "../types";

interface NavItem {
  to: string;
  label: string;
  requiredRoles?: ReadonlyArray<UserRole>;
}

const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { to: "/", label: "Dashboard" },
  { to: "/notifications", label: "Notifications" },
  { to: "/maneuvers", label: "Maneuvers" },
  { to: "/procedures", label: "Procedures" },
  { to: "/shift-log", label: "Shift log" },
  { to: "/audit", label: "Audit log", requiredRoles: ["operator", "admin"] },
];

export default function Layout() {
  const { logout, user } = useAuth();
  const { pathname } = useLocation();

  const visibleItems = NAV_ITEMS.filter((item) => {
    if (!item.requiredRoles) return true;
    if (!user) return false;
    return item.requiredRoles.includes(user.role);
  });

  return (
    <EventTimersProvider>
      <div className="app-shell">
        <header className="app-header">
          <div className="app-title">Daily Operations Dashboard</div>
          <div className="app-header-right">
            {user && <span className="app-user">{user.username}</span>}
            <button type="button" className="logout-btn" onClick={logout}>
              Sign out
            </button>
          </div>
        </header>
        <TimerBanner />
        <div className="app-body">
          <nav className="app-nav">
            {visibleItems.map((item) => (
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
    </EventTimersProvider>
  );
}
