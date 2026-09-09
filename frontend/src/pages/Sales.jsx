import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Undo2 } from "lucide-react";
import { api, ApiError } from "../lib/api";
import { Amount, Button, Profit } from "../components/ui";

const LIMIT = 25;

const date = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
});

export default function Sales() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [voiding, setVoiding] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .listSales({ limit: LIMIT, offset: (page - 1) * LIMIT })
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError("Could not load sales."));
    return () => {
      cancelled = true;
    };
  }, [page, refresh]);

  async function onExport() {
    setExporting(true);
    setError(null);
    try {
      await api.exportSales();
    } catch {
      setError("Could not export. Try again.");
    } finally {
      setExporting(false);
    }
  }

  async function onVoid(sale) {
    // Voiding returns units to the lot, so it changes inventory too. Confirm
    // rather than making a destructive action a single click.
    const label = `${sale.item.name}${sale.item.size ? ` (size ${sale.item.size})` : ""}`;
    if (!window.confirm(`Void this sale of ${label}? Its units return to the lot.`)) {
      return;
    }
    setVoiding(sale.id);
    try {
      await api.voidSale(sale.id);
      setRefresh((n) => n + 1);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.fieldMessage : "Could not void that sale.",
      );
    } finally {
      setVoiding(null);
    }
  }

  const sales = data?.sales ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-3.5">
        <h1 className="expanded text-lg font-semibold">Sales</h1>
        {total > 0 && (
          <span className="tabular text-sm text-muted">{total} recorded</span>
        )}
        <div className="ml-auto">
          <Button onClick={onExport} disabled={exporting || total === 0}>
            <Download className="size-4" aria-hidden="true" />
            {exporting ? "Exporting" : "Export CSV"}
          </Button>
        </div>
      </div>

      {error && (
        <p role="alert" className="px-6 pt-6 text-loss">
          {error}
        </p>
      )}

      {!error && data && sales.length === 0 && (
        <div className="px-6 py-20 text-center">
          <h2 className="expanded text-lg font-semibold">No sales yet</h2>
          <p className="mx-auto mt-2 max-w-sm text-muted">
            Sell something from your inventory and it shows up here with the profit
            it made.
          </p>
        </div>
      )}

      {sales.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-4xl text-left text-sm">
            <thead>
              <tr className="border-y border-line bg-surface text-muted">
                <th scope="col" className="py-2.5 pl-6 pr-3 font-medium">
                  Item
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Sold on
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Marketplace
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Units
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Revenue
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Fees
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Cost
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Net profit
                </th>
                <th scope="col" className="py-2.5 pl-3 pr-6">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sales.map((s) => {
                const fees =
                  Number(s.platform_fee) +
                  Number(s.shipping_cost) +
                  Number(s.other_fees);
                return (
                  <tr key={s.id} className="border-b border-line hover:bg-surface/60">
                    <td className="py-3 pl-6 pr-3">
                      <div className="font-medium">{s.item.name}</div>
                      {s.item.size && (
                        <div className="text-xs text-muted">size {s.item.size}</div>
                      )}
                    </td>
                    <td className="px-3 py-3 text-muted">
                      {date.format(new Date(s.sold_at))}
                    </td>
                    <td className="px-3 py-3">{s.marketplace.name}</td>
                    <td className="px-3 py-3 text-right tabular">{s.quantity_sold}</td>
                    <td className="px-3 py-3 text-right">
                      <Amount value={s.revenue} />
                    </td>
                    <td className="px-3 py-3 text-right text-muted">
                      <Amount value={fees} />
                    </td>
                    <td className="px-3 py-3 text-right text-muted">
                      <Amount value={s.cogs} />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Profit value={s.net_profit} size="sm" />
                    </td>
                    <td className="py-3 pl-3 pr-6 text-right">
                      <Button
                        onClick={() => onVoid(s)}
                        disabled={voiding === s.id}
                        aria-label={`Void sale of ${s.item.name}`}
                      >
                        <Undo2 className="size-4" aria-hidden="true" />
                        {voiding === s.id ? "Voiding" : "Void"}
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {total > 0 && (
        <div className="flex items-center gap-3 px-6 py-4 text-sm">
          <span className="text-muted">
            Page <span className="tabular text-ink">{page}</span> of{" "}
            <span className="tabular text-ink">{pages}</span>
          </span>
          <div className="ml-auto flex gap-2">
            <Button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" aria-hidden="true" />
            </Button>
            <Button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              aria-label="Next page"
            >
              <ChevronRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
