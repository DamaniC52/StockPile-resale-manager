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
} from "lucide-react";
import { useTheme } from "../lib/theme";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/portfolio", label: "Portfolio", icon: LayoutDashboard },
  { to: "/inventory", label: "Inventory", icon: Package },
  { to: "/sales", label: "Sales", icon: Receipt },
];

export default function Sidebar({ collapsed, onToggleCollapse }) {
  const { theme, toggle } = useTheme();
  const { user, signOut } = useAuth();

  const itemClass = ({ isActive }) =>
    [
      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
      isActive
        ? "bg-raised font-medium text-ink shadow-[inset_0_0_0_1px_var(--line)]"
        : "text-muted hover:bg-raised/60 hover:text-ink",
    ].join(" ");

  return (
    <aside
      className={`${collapsed ? "w-16" : "w-60"} flex shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200`}
    >
      <div className="flex items-center gap-2.5 px-4 py-4">
        <span
          className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent font-bold text-accent-ink"
          aria-hidden="true"
        >
          S
        </span>
        {!collapsed && (
          <span className="expanded truncate font-bold tracking-tight">StockPile</span>
        )}
      </div>

      <nav className="flex flex-col gap-1 px-2 py-2">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={itemClass}
            title={collapsed ? label : undefined}
          >
            <Icon className="size-4.5 shrink-0" aria-hidden="true" />
            {!collapsed && <span className="truncate">{label}</span>}
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
          {!collapsed && <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>}
        </button>

        <button
          type="button"
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-raised/60 hover:text-ink"
          title={collapsed ? "Settings" : undefined}
        >
          <Settings className="size-4.5 shrink-0" aria-hidden="true" />
          {!collapsed && <span>Settings</span>}
        </button>

        <button
          type="button"
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-raised/60 hover:text-ink"
          title={collapsed ? "Help" : undefined}
        >
          <HelpCircle className="size-4.5 shrink-0" aria-hidden="true" />
          {!collapsed && <span>Help</span>}
        </button>

        <div className="my-2 border-t border-line" />

        <div className="flex items-center gap-3 px-3 py-1">
          <span
            className="grid size-7 shrink-0 place-items-center rounded-full bg-raised text-xs font-semibold uppercase shadow-[inset_0_0_0_1px_var(--line)]"
            aria-hidden="true"
          >
            {user.email.slice(0, 2)}
          </span>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs text-muted">{user.email}</p>
              <button
                type="button"
                onClick={signOut}
                className="text-xs text-muted underline underline-offset-2 hover:text-ink"
              >
                Sign out
              </button>
            </div>
          )}
        </div>

        <button
          type="button"
          onClick={onToggleCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="mt-1 flex items-center gap-3 rounded-lg px-3 py-2 text-muted hover:bg-raised/60 hover:text-ink"
        >
          {collapsed ? (
            <ChevronsRight className="size-4.5" aria-hidden="true" />
          ) : (
            <ChevronsLeft className="size-4.5" aria-hidden="true" />
          )}
        </button>
      </div>
    </aside>
  );
}
