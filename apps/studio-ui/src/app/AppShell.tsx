import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { PrivacyBadge } from "../components/Misc";
import { ErrorBoundary } from "./ErrorBoundary";

interface NavItem {
  to: string;
  label: string;
  end?: boolean;
}

const WORKING: NavItem[] = [
  { to: "/", label: "Library", end: true },
  { to: "/new", label: "New book" },
  { to: "/import", label: "Import" },
  { to: "/manuscripts", label: "Manuscripts" },
  { to: "/series", label: "Series" },
  { to: "/knowledge", label: "Knowledge" },
  { to: "/publishing", label: "Publishing" },
  { to: "/jobs", label: "AI jobs" },
  { to: "/ai-settings", label: "AI settings" },
  { to: "/voice", label: "Author voice" },
  { to: "/activity", label: "Activity" },
  { to: "/help", label: "Help" },
];

/** Later-phase sections: visible so the roadmap is honest, but not navigable. */
export const LATER: { label: string; phase: string }[] = [];

export function AppShell() {
  const location = useLocation();
  // The small-screen menu is open only for the page it was opened on, so navigating closes it.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === location.pathname;

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="shell">
        <nav className="nav" aria-label="Main" id="main-nav" data-open={open}>
          <NavLink to="/" className="brand">
            Personal Book Studio
            <small>Your books, on this computer</small>
          </NavLink>
          <ul>
            {WORKING.slice(0, 6).map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end} className="nav-link">
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
          {LATER.length ? (
            <>
              <p className="nav-group-label" id="later-label">
                Coming in later phases
              </p>
              <ul aria-labelledby="later-label">
                {LATER.map((item) => (
                  <li key={item.label}>
                    <span className="nav-disabled" aria-disabled="true">
                      {item.label}
                      <small>Not yet implemented (Phase {item.phase})</small>
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          <p className="nav-group-label" id="studio-label">
            Studio
          </p>
          <ul aria-labelledby="studio-label">
            {WORKING.slice(6).map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} className="nav-link">
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="main">
          <div className="topbar">
            <button
              type="button"
              className="btn btn-small menu-toggle"
              aria-expanded={open}
              aria-controls="main-nav"
              onClick={() => setOpenOn(open ? null : location.pathname)}
            >
              Menu
            </button>
            <PrivacyBadge />
          </div>
          <main id="main" className="content" tabIndex={-1}>
            <ErrorBoundary resetKey={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </>
  );
}
