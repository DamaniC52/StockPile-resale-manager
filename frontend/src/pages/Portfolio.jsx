import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { api } from "../lib/api";
import { Amount, Profit, Segmented } from "../components/ui";
import { useTheme } from "../lib/theme";

const RANGES = [
  { value: "1m", label: "1m" },
  { value: "3m", label: "3m" },
  { value: "1y", label: "1y" },
  { value: "ytd", label: "Ytd" },
  { value: "all", label: "All" },
];

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const monthLabel = new Intl.DateTimeFormat("en-US", { month: "short", year: "2-digit" });

/** Recharts needs real colour values, so the theme tokens are read from CSS. */
function useChartColors() {
  const { theme } = useTheme();
  return useMemo(() => {
    const s = getComputedStyle(document.documentElement);
    const get = (n) => s.getPropertyValue(n).trim();
    return {
      gain: get("--gain"),
      loss: get("--loss"),
      line: get("--line"),
      muted: get("--muted"),
    };
  }, [theme]);
}

export default function Portfolio() {
  const [summary, setSummary] = useState(null);
  const [series, setSeries] = useState(null);
  const [byMarketplace, setByMarketplace] = useState([]);
  const [range, setRange] = useState("all");
  const [error, setError] = useState(null);
  const colors = useChartColors();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // Every figure below is computed in Postgres. The browser receives a dozen
    // numbers rather than every sale that produced them.
    Promise.all([
      api.dashboardSummary(range),
      api.profitOverTime(range, "month"),
      api.profitByMarketplace(),
    ])
      .then(([s, t, m]) => {
        if (cancelled) return;
        setSummary(s);
        setSeries(t);
        setByMarketplace(m);
      })
      .catch(() => !cancelled && setError("Could not load the dashboard."));
    return () => {
      cancelled = true;
    };
  }, [range]);

  // The API returns per-period profit; the chart shows the running total, which
  // is a one-line scan rather than something worth a second endpoint.
  const cumulative = useMemo(() => {
    if (!series) return [];
    let running = 0;
    return series.map((p) => {
      running += Number(p.net_profit);
      return {
        t: new Date(p.period).getTime(),
        value: Number(running.toFixed(2)),
        period: Number(p.net_profit),
      };
    });
  }, [series]);

  if (error) {
    return (
      <div>
        <div className="border-b border-line px-6 py-3.5">
          <h1 className="expanded text-lg font-semibold">Portfolio</h1>
        </div>
        <p role="alert" className="px-6 py-10 text-loss">
          {error}
        </p>
      </div>
    );
  }

  if (!summary) return <div className="px-6 py-10 text-muted">Loading…</div>;

  const windowed = range !== "all" && summary.period_sale_count > 0;
  const up = Number(summary.period_net_profit) >= 0;
  const chartColor = Number(summary.net_profit) >= 0 ? colors.gain : colors.loss;

  return (
    <div>
      <div className="border-b border-line px-6 py-3.5">
        <h1 className="expanded text-lg font-semibold">Portfolio</h1>
      </div>

      <div className="max-w-5xl px-6 py-6">
        <p className="text-sm text-muted">Realized profit</p>

        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <Profit value={summary.net_profit} size="figure" />
          {windowed && (
            <span
              className={`inline-flex items-center gap-1 text-sm font-medium ${up ? "text-gain" : "text-loss"}`}
            >
              {up ? (
                <ArrowUpRight className="size-4" aria-hidden="true" />
              ) : (
                <ArrowDownRight className="size-4" aria-hidden="true" />
              )}
              <span className="tabular">
                {up ? "+" : "−"}
                {money.format(Math.abs(Number(summary.period_net_profit)))}
              </span>
              <span className="text-muted">
                this {RANGES.find((r) => r.value === range)?.label.toLowerCase()}
              </span>
            </span>
          )}
        </div>

        <p className="mt-2 text-sm text-muted">
          <span className="tabular text-ink">{summary.units_in_stock}</span> units in
          stock, <Amount value={summary.capital_tied_up} className="text-ink" /> tied up
          across <span className="tabular text-ink">{summary.lot_count}</span> lots
        </p>

        <div className="mt-5">
          <Segmented
            label="Time range"
            value={range}
            onChange={setRange}
            options={RANGES}
          />
        </div>

        <div className="mt-6 h-64">
          {cumulative.length < 2 ? (
            <div className="grid h-full place-items-center rounded-xl bg-surface text-center text-sm text-muted">
              <p className="max-w-xs">
                {cumulative.length === 0
                  ? "No sales in this period. Log one and the profit curve appears here."
                  : "One month of sales so far. The curve appears once there are two."}
              </p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={cumulative}
                margin={{ top: 4, right: 4, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={chartColor} stopOpacity={0.22} />
                    <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={colors.line} vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(t) => monthLabel.format(new Date(t))}
                  stroke={colors.muted}
                  tickLine={false}
                  axisLine={false}
                  fontSize={12}
                />
                <YAxis
                  tickFormatter={(v) => `$${v}`}
                  stroke={colors.muted}
                  tickLine={false}
                  axisLine={false}
                  width={64}
                  fontSize={12}
                />
                <Tooltip
                  formatter={(v, _n, p) => [
                    `${money.format(v)} (${p.payload.period >= 0 ? "+" : "−"}${money.format(Math.abs(p.payload.period))} that month)`,
                    "Running total",
                  ]}
                  labelFormatter={(t) => monthLabel.format(new Date(t))}
                  contentStyle={{
                    background: "var(--raised)",
                    border: "1px solid var(--line)",
                    borderRadius: 8,
                    color: "var(--ink)",
                    fontSize: 13,
                  }}
                />
                {/* Profit changes when a sale is recorded, not continuously. */}
                <Area
                  type="stepAfter"
                  dataKey="value"
                  stroke={chartColor}
                  strokeWidth={2}
                  fill="url(#fill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>

        {byMarketplace.length > 0 && (
          <div className="mt-10">
            <h2 className="expanded font-semibold">Where it sold</h2>
            <table className="mt-3 w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line text-muted">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    Marketplace
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Sales
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Revenue
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    Fees
                  </th>
                  <th scope="col" className="py-2 pl-3 text-right font-medium">
                    Net profit
                  </th>
                </tr>
              </thead>
              <tbody>
                {byMarketplace.map((m) => (
                  <tr key={m.slug} className="border-b border-line/70">
                    <td className="py-2.5 pr-3 font-medium">{m.marketplace}</td>
                    <td className="px-3 py-2.5 text-right tabular">{m.sale_count}</td>
                    <td className="px-3 py-2.5 text-right">
                      <Amount value={m.revenue} />
                    </td>
                    <td className="px-3 py-2.5 text-right text-muted">
                      <Amount value={m.platform_fees} />
                    </td>
                    <td className="py-2.5 pl-3 text-right">
                      <Profit value={m.net_profit} size="sm" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
