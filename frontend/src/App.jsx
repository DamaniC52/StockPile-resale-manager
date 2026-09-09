import { useState } from "react";
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

  return (
    <div className="flex min-h-dvh">
      <Sidebar collapsed={collapsed} onToggleCollapse={() => setCollapsed((c) => !c)} />
      <main className="min-w-0 flex-1">{children}</main>
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
