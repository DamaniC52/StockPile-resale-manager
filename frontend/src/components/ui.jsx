const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

/** A cost or price. Not a result, so it carries no colour. */
export function Amount({ value, className = "" }) {
  return <span className={`tabular ${className}`}>{money.format(Number(value))}</span>;
}

/**
 * A profit or loss.
 *
 * Colour alone cannot carry this: the two hues are near-identical under
 * deuteranopia. The sign is always rendered and weight reinforces it, so
 * colour is the third signal rather than the only one.
 */
export function Profit({ value, className = "", size = "base" }) {
  const n = Number(value);
  const up = n >= 0;
  const sizes = {
    sm: "text-sm font-medium",
    base: "font-semibold",
    figure: "text-figure font-bold expanded",
  };
  return (
    <span className={`tabular ${sizes[size]} ${up ? "text-gain" : "text-loss"} ${className}`}>
      {up ? "+" : "−"}
      {money.format(Math.abs(n))}
    </span>
  );
}

/** Status pill. Muted by default so it labels without competing with money. */
export function Badge({ tone = "neutral", children }) {
  const tones = {
    neutral: "bg-raised text-muted shadow-[inset_0_0_0_1px_var(--line)]",
    gain: "bg-gain-soft text-gain",
    loss: "bg-loss-soft text-loss",
  };
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/** Segmented control — one visible choice among a few, unlike a select. */
export function Segmented({ value, onChange, options, label }) {
  return (
    <div role="group" aria-label={label} className="flex rounded-lg bg-surface p-0.5">
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
            className={`rounded-[7px] px-3 py-1.5 text-sm transition-colors ${
              active
                ? "bg-raised font-medium text-ink shadow-[0_1px_2px_rgba(0,0,0,.06),inset_0_0_0_1px_var(--line)]"
                : "text-muted hover:text-ink"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export function Button({ variant = "secondary", className = "", ...props }) {
  const variants = {
    primary: "bg-accent text-accent-ink hover:opacity-90",
    secondary:
      "bg-raised text-ink shadow-[inset_0_0_0_1px_var(--line)] hover:bg-surface",
    ghost: "text-muted hover:text-ink",
  };
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-40 ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

/** An applied filter, shown as a removable chip so active state is never hidden. */
export function FilterChip({ field, value, onRemove }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-lg bg-raised py-1 pl-2.5 pr-1.5 text-sm shadow-[inset_0_0_0_1px_var(--line)]">
      <span className="text-muted">{field} is</span>
      <span className="rounded bg-surface px-1.5 py-0.5 font-medium">{value}</span>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${field} filter`}
        className="grid size-5 place-items-center rounded text-muted hover:text-ink"
      >
        ×
      </button>
    </span>
  );
}
