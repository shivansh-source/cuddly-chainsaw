import { Navigate, NavLink, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { resetCompanyCache, useAuth } from "./auth";
import { Icon } from "./components/ui";
import {
  ActivityPage, BuyerOverview, BuyerRequests, BuyerSuppliers, LoginPage, SellerCatalog, SellerInbox,
  WorkspaceRoute,
} from "./pages/Pages";
import { Landing } from "./pages/Landing";
import type { Role } from "./types";

const NAV: Record<Role, { to: string; label: string; icon: string; end?: boolean }[]> = {
  buyer: [
    { to: "/buyer", label: "Overview", icon: "overview", end: true },
    { to: "/buyer/requests", label: "Requests", icon: "requests" },
    { to: "/buyer/suppliers", label: "Suppliers", icon: "suppliers" },
    { to: "/buyer/activity", label: "Activity", icon: "activity" },
  ],
  seller: [
    { to: "/seller", label: "Inbox", icon: "inbox", end: true },
    { to: "/seller/catalog", label: "Catalog & pricing", icon: "catalog" },
    { to: "/seller/activity", label: "Activity", icon: "activity" },
  ],
};

function Shell({ role }: { role: Role }) {
  const { session, logout } = useAuth();
  const location = useLocation();
  if (!session) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (session.role !== role) return <Navigate to={session.role === "buyer" ? "/buyer" : "/seller"} replace />;
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark" aria-hidden="true">N</span><span>The Negotiator</span></div>
        <span className="brand-sub">AI procurement operations</span>
        <nav aria-label="Main">
          {NAV[role].map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? "nav-on" : ""}`}>
              <Icon name={n.icon} /> <span>{n.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="me">
          <div className="me-avatar" aria-hidden="true">{(session.company_name ?? session.email)[0]?.toUpperCase()}</div>
          <div className="me-text">
            <strong>{session.company_name ?? session.company_id}</strong>
            <span className="muted">{role === "buyer" ? "Buyer" : "Supplier"} · {session.email}</span>
          </div>
          <button className="icon-btn" aria-label="Sign out" title="Sign out" onClick={() => { resetCompanyCache(); logout(); }}>
            <Icon name="logout" />
          </button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  );
}

function Home() {
  const { session } = useAuth();
  if (!session) return <Navigate to="/login" replace />;
  return <Navigate to={session.role === "buyer" ? "/buyer" : "/seller"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/buyer" element={<Shell role="buyer" />}>
        <Route index element={<BuyerOverview />} />
        <Route path="requests" element={<BuyerRequests />} />
        <Route path="rfq/:id" element={<WorkspaceRoute />} />
        <Route path="suppliers" element={<BuyerSuppliers />} />
        <Route path="activity" element={<ActivityPage />} />
      </Route>
      <Route path="/seller" element={<Shell role="seller" />}>
        <Route index element={<SellerInbox />} />
        <Route path="rfq/:id" element={<WorkspaceRoute />} />
        <Route path="catalog" element={<SellerCatalog />} />
        <Route path="activity" element={<ActivityPage />} />
      </Route>
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
