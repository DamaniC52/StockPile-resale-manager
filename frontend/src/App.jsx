import { useState } from "react";
import { Menu } from "lucide-react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import Sidebar from "./components/Sidebar";
import SignIn from "./pages/SignIn";
import Inventory from "./pages/Inventory";
import Portfolio from "./pages/Portfolio";
import Sales from "./pages/Sales";

function Shell({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="flex min-h-dvh">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        open={navOpen}
        onClose={() => setNavOpen(false)}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        {/* The only way to reach navigation once the sidebar is off-canvas. */}
        <div className="flex items-center gap-3 border-b border-line px-4 py-2.5 md:hidden">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface hover:text-ink"
          >
            <Menu className="size-5" aria-hidden="true" />
          </button>
          <span className="expanded font-bold tracking-tight">StockPile</span>
        </div>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/signin" replace />;
  return <Shell>{children}</Shell>;
}

function Routing() {
  const { user, loading } = useAuth();
  if (loading) return null;

  return (
    <Routes>
      <Route
        path="/signin"
        element={user ? <Navigate to="/portfolio" replace /> : <SignIn />}
      />
      <Route
        path="/portfolio"
        element={
          <Protected>
            <Portfolio />
          </Protected>
        }
      />
      <Route
        path="/inventory"
        element={
          <Protected>
            <Inventory />
          </Protected>
        }
      />
      <Route
        path="/sales"
        element={
          <Protected>
            <Sales />
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/portfolio" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Routing />
      </AuthProvider>
    </ThemeProvider>
  );
}
