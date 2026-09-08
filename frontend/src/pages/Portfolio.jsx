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
  { value: "1m", label: "1m", days: 30 },
  { value: "3m", label: "3m", days: 90 },
  { value: "ytd", label: "Ytd", days: null },
  { value: "all", label: "All", days: Infinity },
];

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });

/** Recharts needs real colour values, so the theme tokens are read from CSS. */
function useChartColors() {
  const { theme } = useTheme();
  return useMemo(() => {
    const s = getComputedStyle(document.documentElement);
    const get = (n) => s.getPropertyValue(n).trim();
    return { gain: get("--gain"), loss: get("--loss"), line: get("--line"), muted: get("--muted") };
    // theme is the dependency: the variables resolve differently after it changes.
  }, [theme]);
}

function startOf(range) {
  if (range === "all") return new Date(0);
  if (range === "ytd") return new Date(new Date().getFullYear(), 0, 1);
  const days = RANGES.find((r) => r.value === range).days;
  return new Date(Date.now() - days * 86400000);
}

export default function Portfolio() {
  const [sales, setSales] = useState(null);
  const [items, setItems] = useState(null);
  const [range, setRange] = useState("all");
  const colors = useChartColors();

  useEffect(() => {
    Promise.all([api.listSales({ limit: 100 }), api.listItems({ limit: 100 })])
      .then(([s, i]) => {
        setSales(s.sales);
        setItems(i.items);
      })
      .catch(() => {
        setSales([]);
        setItems([]);
      });
  }, []);

  const view = useMemo(() => {
    if (!sales || !items) return null;

    const from = startOf(range);
    const inRange = sales.filter((s) => new Date(s.sold_at) >= from);
    const before = sales.filter((s) => new Date(s.sold_at) < from);

    const sum = (rows) => rows.reduce((n, s) => n + Number(s.net_profit), 0);
    const periodProfit = sum(inRange);
    const priorProfit = sum(before);
    const totalProfit = periodProfit + priorProfit;

    const tiedUp = items.reduce(
      (n, i) => n + Number(i.unit_cost) * i.quantity_remaining,
      0,
    );
    const units = items.reduce((n, i) => n + i.quantity_remaining, 0);

    // Cumulative realized profit, oldest first. Every point is a real sale —
    // nothing here is interpolated or invented.
    const chronological = [...sales].sort(
      (a, b) => new Date(a.sold_at) - new Date(b.sold_at),
    );
    let running = 0;
    const series = chronological.map((s) => {
      running += Number(s.net_profit);
      return { t: new Date(s.sold_at).getTime(), value: Number(running.toFixed(2)) };
    });

    // Percentage change is undefined against a zero base, so it is shown only
    // when there is a prior figure to compare against.
    const pct = priorProfit !== 0 ? (periodProfit / Math.abs(priorProfit)) * 100 : null;

    return { totalProfit, periodProfit, pct, tiedUp, units, series, count: sales.length };
  }, [sales, items, range]);

  if (!view) return <div className="px-6 py-10 text-muted">Loading…</div>;

  const up = view.periodProfit >= 0;

  return (
    <div>
      <div className="border-b border-line px-6 py-3.5">
        <h1 className="expanded text-lg font-semibold">Portfolio</h1>
      </div>

      <div className="px-6 py-6">
        <p className="text-sm text-muted">Realized profit</p>

        <div className="mt-1.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <Profit value={view.totalProfit} size="figure" />
          {view.count > 0 && (
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
                {money.format(Math.abs(view.periodProfit))}
              </span>
              {view.pct !== null && (
                <span className="tabular text-muted">
                  {view.pct >= 0 ? "+" : "−"}
                  {Math.abs(view.pct).toFixed(1)}%
                </span>
              )}
            </span>
          )}
        </div>

        <p className="mt-2 text-sm text-muted">
          <span className="tabular text-ink">{view.units}</span> units in stock,{" "}
          <Amount value={view.tiedUp} className="text-ink" /> tied up across{" "}
          <span className="tabular text-ink">{items.length}</span> lots
        </p>

        <div className="mt-5">
          <Segmented
            label="Time range"
            value={range}
            onChange={setRange}
            options={RANGES.map(({ value, label }) => ({ value, label }))}
          />
        </div>

        <div className="mt-6 h-64">
          {view.series.length < 2 ? (
            <div className="grid h-full place-items-center rounded-xl bg-surface text-center text-sm text-muted">
              <p className="max-w-xs">
                Log at least two sales and the profit curve appears here.
              </p>
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={view.series} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={colors.gain} stopOpacity={0.22} />
                    <stop offset="100%" stopColor={colors.gain} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke={colors.line} vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={(t) => day.format(new Date(t))}
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
                  formatter={(v) => [money.format(v), "Cumulative profit"]}
                  labelFormatter={(t) => day.format(new Date(t))}
                  contentStyle={{
                    background: "var(--raised)",
                    border: `1px solid var(--line)`,
                    borderRadius: 8,
                    color: "var(--ink)",
                    fontSize: 13,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke={colors.gain}
                  strokeWidth={2}
                  fill="url(#fill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}
