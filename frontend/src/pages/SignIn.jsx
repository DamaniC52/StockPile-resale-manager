import { useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";

export default function SignIn() {
  const { signIn, register } = useAuth();
  const [mode, setMode] = useState("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const registering = mode === "register";

  async function onSubmit(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await (registering ? register(email, password) : signIn(email, password));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.fieldMessage : "Could not reach the server",
      );
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh grid place-items-center px-6">
      <div className="w-full max-w-sm">
        <h1 className="expanded text-3xl font-bold tracking-tight">StockPile</h1>
        <p className="mt-2 text-muted">
          What you bought, what it sold for, what you kept.
        </p>

        <form onSubmit={onSubmit} className="mt-10 space-y-5">
          <div>
            <label htmlFor="email" className="block text-sm font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1.5 w-full rounded border border-line px-3 py-2 focus:border-ink focus:outline-none"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={registering ? 8 : undefined}
              autoComplete={registering ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1.5 w-full rounded border border-line px-3 py-2 focus:border-ink focus:outline-none"
            />
            {registering && (
              <p className="mt-1.5 text-sm text-muted">At least 8 characters.</p>
            )}
          </div>

          {/* Errors state what happened and what to do, in the interface's
              voice. No apology, no vague "something went wrong". */}
          {error && (
            <p role="alert" className="text-sm text-loss">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded bg-ink px-4 py-2.5 font-medium text-ground disabled:opacity-50"
          >
            {busy
              ? registering
                ? "Creating account"
                : "Signing in"
              : registering
                ? "Create account"
                : "Sign in"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => {
            setMode(registering ? "signin" : "register");
            setError(null);
          }}
          className="mt-6 text-sm text-muted underline underline-offset-4 hover:text-ink"
        >
          {registering ? "Already have an account? Sign in" : "Create an account"}
        </button>
      </div>
    </div>
  );
}
