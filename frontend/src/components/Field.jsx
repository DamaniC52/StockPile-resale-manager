const base =
  "w-full rounded-lg bg-raised px-3 py-2 shadow-[inset_0_0_0_1px_var(--line)] placeholder:text-muted focus:outline-none focus-visible:outline-2";

/**
 * Label, control, hint and error as one unit, so a field can never ship with
 * its label wired to the wrong input or its error unannounced.
 */
export default function Field({ id, label, hint, error, prefix, children, ...props }) {
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ");

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>

      <div className={prefix ? "relative mt-1.5" : "mt-1.5"}>
        {prefix && (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">
            {prefix}
          </span>
        )}
        {children ?? (
          <input
            id={id}
            aria-describedby={describedBy || undefined}
            aria-invalid={error ? true : undefined}
            className={`${base} ${prefix ? "pl-7" : ""} ${error ? "shadow-[inset_0_0_0_1px_var(--loss)]" : ""}`}
            {...props}
          />
        )}
      </div>

      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-loss">
          {error}
        </p>
      )}
    </div>
  );
}

export { base as fieldClass };
