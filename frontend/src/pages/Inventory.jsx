import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Plus, Search } from "lucide-react";
import { api } from "../lib/api";
import { Amount, Badge, Button, FilterChip, Segmented } from "../components/ui";
import AddItemForm from "../components/AddItemForm";
import LogSaleForm from "../components/LogSaleForm";

const LIMIT = 25;

const CONDITIONS = [
  { value: "", label: "Any condition" },
  { value: "new", label: "New" },
  { value: "like_new", label: "Like new" },
  { value: "used", label: "Used" },
  { value: "damaged", label: "Damaged" },
];

const CONDITION_LABEL = Object.fromEntries(CONDITIONS.map((c) => [c.value, c.label]));

const STOCK_TABS = [
  { value: "all", label: "All" },
  { value: "in", label: "In stock" },
  { value: "out", label: "Sold out" },
];

const STATUS = {
  in_stock: { label: "In stock", tone: "neutral" },
  partially_sold: { label: "Part sold", tone: "neutral" },
  // Neutral, not green: colour is reserved for money, and a green status
  // badge competes with the profit figures for the same signal.
  sold_out: { label: "Sold out", tone: "neutral" },
};

export default function Inventory() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [stock, setStock] = useState("all");
  const [condition, setCondition] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [selling, setSelling] = useState(null);
  // Bumping this re-runs the fetch effect after a write, so the table and the
  // portfolio figures reflect the change without a full reload.
  const [refresh, setRefresh] = useState(0);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .listItems({
        limit: LIMIT,
        offset: (page - 1) * LIMIT,
        brand_or_name: query || undefined,
        in_stock: stock === "all" ? undefined : stock === "in",
        condition: condition || undefined,
      })
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setError("Could not load inventory."));
    return () => {
      cancelled = true;
    };
  }, [query, stock, condition, page, refresh]);

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / LIMIT));
  const filtered = stock !== "all" || condition !== "";

  async function onExport() {
    setExporting(true);
    setError(null);
    try {
      // The current filters, but not the search term: an export is a record of
      // what you hold, and quietly exporting only search matches produces an
      // incomplete spreadsheet someone then relies on.
      await api.exportItems({
        in_stock: stock === "all" ? undefined : stock === "in",
        condition: condition || undefined,
      });
    } catch {
      setError("Could not export. Try again.");
    } finally {
      setExporting(false);
    }
  }

  function reset() {
    setStock("all");
    setCondition("");
    setPage(1);
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-6 py-3.5">
        <h1 className="expanded text-lg font-semibold">Inventory</h1>
        <div className="ml-auto flex items-center gap-2">
          <Button onClick={onExport} disabled={exporting || total === 0}>
            <Download className="size-4" aria-hidden="true" />
            {exporting ? "Exporting" : "Export CSV"}
          </Button>
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus className="size-4" aria-hidden="true" />
            Add item
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 px-6 py-4">
        <div className="relative min-w-56 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted"
            aria-hidden="true"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
            placeholder="Search inventory"
            aria-label="Search inventory"
            className="w-full rounded-lg bg-raised py-2 pl-9 pr-3 shadow-[inset_0_0_0_1px_var(--line)] placeholder:text-muted focus:outline-none focus-visible:outline-2"
          />
        </div>

        <Segmented
          label="Stock filter"
          value={stock}
          onChange={(v) => {
            setStock(v);
            setPage(1);
          }}
          options={STOCK_TABS}
        />

        <select
          value={condition}
          onChange={(e) => {
            setCondition(e.target.value);
            setPage(1);
          }}
          aria-label="Condition filter"
          className="rounded-lg bg-raised px-3 py-2 text-sm shadow-[inset_0_0_0_1px_var(--line)]"
        >
          {CONDITIONS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      {/* Applied filters stay visible as chips: a filtered empty table with no
          visible cause is one of the easiest ways to confuse someone. */}
      {filtered && (
        <div className="flex flex-wrap items-center gap-2 px-6 pb-4">
          {stock !== "all" && (
            <FilterChip
              field="Stock"
              value={STOCK_TABS.find((t) => t.value === stock).label}
              onRemove={() => setStock("all")}
            />
          )}
          {condition && (
            <FilterChip
              field="Condition"
              value={CONDITION_LABEL[condition]}
              onRemove={() => setCondition("")}
            />
          )}
          <button
            type="button"
            onClick={reset}
            className="ml-auto text-sm font-medium text-muted hover:text-ink"
          >
            Clear all
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="px-6 text-loss">
          {error}
        </p>
      )}

      {!error && data && items.length === 0 && (
        <div className="px-6 py-20 text-center">
          <h2 className="expanded text-lg font-semibold">
            {query || filtered ? "Nothing matches those filters" : "No inventory yet"}
          </h2>
          <p className="mx-auto mt-2 max-w-sm text-muted">
            {query || filtered
              ? "Widen the filters to see more of your inventory."
              : "Add the first thing you bought to resell. Its profit shows up here once it sells."}
          </p>
          {!query && !filtered && (
            <Button variant="primary" className="mt-5" onClick={() => setAdding(true)}>
              <Plus className="size-4" aria-hidden="true" />
              Add item
            </Button>
          )}
        </div>
      )}

      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-4xl text-left text-sm">
            <thead>
              <tr className="border-y border-line bg-surface text-muted">
                <th scope="col" className="py-2.5 pl-6 pr-3 font-medium">
                  Item
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Size
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Source
                </th>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  Status
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Left
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Unit cost
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Purchase total
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  Tied up
                </th>
                <th scope="col" className="py-2.5 pl-3 pr-6">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const status = STATUS[item.stock_status];
                const purchaseTotal =
                  Number(item.unit_cost) * item.quantity +
                  Number(item.acquisition_fee_total);
                return (
                  <tr key={item.id} className="border-b border-line hover:bg-surface/60">
                    <td className="py-3 pl-6 pr-3">
                      <div className="font-medium">{item.name}</div>
                      <div className="text-xs text-muted">
                        {CONDITION_LABEL[item.condition]}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className="tabular font-medium">{item.size ?? "—"}</span>
                    </td>
                    <td className="px-3 py-3 text-muted">{item.source ?? "—"}</td>
                    <td className="px-3 py-3">
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </td>
                    <td className="px-3 py-3 text-right tabular">
                      {item.quantity_remaining}
                      <span className="text-muted">/{item.quantity}</span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Amount value={item.unit_cost} />
                    </td>
                    <td className="px-3 py-3 text-right text-muted">
                      <Amount value={purchaseTotal} />
                    </td>
                    <td className="px-3 py-3 text-right">
                      <Amount value={Number(item.unit_cost) * item.quantity_remaining} />
                    </td>
                    <td className="py-3 pl-3 pr-6 text-right">
                      {item.quantity_remaining > 0 && (
                        <Button onClick={() => setSelling(item)}>Sell</Button>
                      )}
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
          <span className="text-muted">·</span>
          <span className="tabular text-muted">{total} items</span>
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

      <AddItemForm
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={() => {
          setPage(1);
          setRefresh((n) => n + 1);
        }}
      />

      <LogSaleForm
        open={selling !== null}
        item={selling}
        onClose={() => setSelling(null)}
        onLogged={() => setRefresh((n) => n + 1)}
      />
    </div>
  );
}
