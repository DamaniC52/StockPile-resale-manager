import { useEffect } from "react";
import { NavLink } from "react-router-dom";
import {
  ChevronsLeft,
  ChevronsRight,
  HelpCircle,
  LayoutDashboard,
  Moon,
  Package,
  Receipt,
  Settings,
  Sun,
  X,
} from "lucide-react";
import { useTheme } from "../lib/theme";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/portfolio", label: "Portfolio", icon: LayoutDashboard },
  { to: "/inventory", label: "Inventory", icon: Package },
  { to: "/sales", label: "Sales", icon: Receipt },
];

export default function Sidebar({ collapsed, onToggleCollapse, open, onClose }) {
  const { theme, toggle } = useTheme();
  const { user, signOut } = useAuth();

  // Escape closes the mobile drawer, matching the dialog convention.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Collapse is a desktop affordance only; on mobile the drawer is full width.
  const width = collapsed ? "md:w-16" : "md:w-60";

  const itemClass = ({ isActive }) =>
    [
      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
      isActive
        ? "bg-raised font-medium text-ink shadow-[inset_0_0_0_1px_var(--line)]"
        : "text-muted hover:bg-raised/60 hover:text-ink",
    ].join(" ");

  // Labels are hidden only when collapsed AND on a desktop viewport.
  const labelClass = collapsed ? "truncate md:hidden" : "truncate";

  return (
    <>
      {/* Backdrop, mobile only. Clicking it closes the drawer. */}
      {open && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
        />
      )}

      <aside
        className={[
          // Off-canvas by default, slid in when open; a normal flex child at md.
          "fixed inset-y-0 left-0 z-40 w-64 shrink-0 border-r border-line bg-surface",
          "flex flex-col transition-transform duration-200",
          open ? "translate-x-0" : "-translate-x-full",
          "md:static md:translate-x-0 md:transition-[width]",
          width,
        ].join(" ")}
      >
        <div className="flex items-center gap-2.5 px-4 py-4">
          <span
            className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent font-bold text-accent-ink"
            aria-hidden="true"
          >
            S
          </span>
          <span className={`expanded font-bold tracking-tight ${labelClass}`}>
            StockPile
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="ml-auto grid size-8 place-items-center rounded-lg text-muted hover:bg-raised hover:text-ink md:hidden"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>

        <nav className="flex flex-col gap-1 px-2 py-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={itemClass}
              // Navigating on mobile should dismiss the drawer.
              onClick={onClose}
              title={collapsed ? label : undefined}
            >
              <Icon className="size-4.5 shrink-0" aria-hidden="true" />
              <span className={labelClass}>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-1 px-2 pb-3">
          <button
            type="button"
            onClick={toggle}
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-raised/60 hover:text-ink"
            title={collapsed ? "Switch theme" : undefined}
          >
            {theme === "dark" ? (
              <Sun className="size-4.5 shrink-0" aria-hidden="true" />
            ) : (
              <Moon className="size-4.5 shrink-0" aria-hidden="true" />
            )}
            <span className={labelClass}>
              {theme === "dark" ? "Light mode" : "Dark mode"}
            </span>
          </button>

          <button
            type="button"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-raised/60 hover:text-ink"
            title={collapsed ? "Settings" : undefined}
          >
            <Settings className="size-4.5 shrink-0" aria-hidden="true" />
            <span className={labelClass}>Settings</span>
          </button>

          <button
            type="button"
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-raised/60 hover:text-ink"
            title={collapsed ? "Help" : undefined}
          >
            <HelpCircle className="size-4.5 shrink-0" aria-hidden="true" />
            <span className={labelClass}>Help</span>
          </button>

          <div className="my-2 border-t border-line" />

          <div className="flex items-center gap-3 px-3 py-1">
            <span
              className="grid size-7 shrink-0 place-items-center rounded-full bg-raised text-xs font-semibold uppercase shadow-[inset_0_0_0_1px_var(--line)]"
              aria-hidden="true"
            >
              {user.email.slice(0, 2)}
            </span>
            <div className={`min-w-0 flex-1 ${collapsed ? "md:hidden" : ""}`}>
              <p className="truncate text-xs text-muted">{user.email}</p>
              <button
                type="button"
                onClick={signOut}
                className="text-xs text-muted underline underline-offset-2 hover:text-ink"
              >
                Sign out
              </button>
            </div>
          </div>

          {/* Collapsing is meaningless in a full-width drawer. */}
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="mt-1 hidden items-center gap-3 rounded-lg px-3 py-2 text-muted hover:bg-raised/60 hover:text-ink md:flex"
          >
            {collapsed ? (
              <ChevronsRight className="size-4.5" aria-hidden="true" />
            ) : (
              <ChevronsLeft className="size-4.5" aria-hidden="true" />
            )}
          </button>
        </div>
      </aside>
    </>
  );
}
