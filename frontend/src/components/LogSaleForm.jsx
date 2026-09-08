import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../lib/api";
import { Button, Profit } from "./ui";
import Field, { fieldClass } from "./Field";
import Modal from "./Modal";

const nowLocal = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

export default function LogSaleForm({ open, item, onClose, onLogged }) {
  const [marketplaces, setMarketplaces] = useState([]);
  const [form, setForm] = useState(null);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.listMarketplaces().then(setMarketplaces).catch(() => setMarketplaces([]));
  }, [open]);

  useEffect(() => {
    if (!open || !item) return;
    setForm({
      marketplace_id: "",
      quantity_sold: "1",
      unit_price: "",
      platform_fee: "",
      shipping_cost: "",
      sold_at: nowLocal(),
    });
    setErrors({});
  }, [open, item]);

  const set = (k) => (e) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    // Clear this field's error as soon as it is edited. Waiting for the next
    // submit leaves a red message under a field the user has already fixed.
    setErrors((prev) => (prev[k] ? { ...prev, [k]: undefined } : prev));
  };

  /** Picking a marketplace pre-fills its typical fee from the price entered. */
  function onMarketplaceChange(e) {
    const id = e.target.value;
    const mp = marketplaces.find((m) => String(m.id) === id);
    setErrors((prev) => (prev.marketplace_id ? { ...prev, marketplace_id: undefined } : prev));
    setForm((f) => {
      const price = Number(f.unit_price) || 0;
      const qty = Number(f.quantity_sold) || 0;
      const suggested =
        mp?.default_fee_pct && price > 0
          ? (price * qty * mp.default_fee_pct).toFixed(2)
          : f.platform_fee;
      return { ...f, marketplace_id: id, platform_fee: suggested };
    });
  }

  // Mirrors the server's formula so the number moves as you type. The server
  // remains the source of truth; this is a preview, not a second calculator.
  const preview = useMemo(() => {
    if (!form || !item) return null;
    const qty = Number(form.quantity_sold) || 0;
    const revenue = (Number(form.unit_price) || 0) * qty;
    const fees =
      (Number(form.platform_fee) || 0) + (Number(form.shipping_cost) || 0);
    const feeShare =
      item.quantity > 0
        ? (Number(item.acquisition_fee_total) * qty) / item.quantity
        : 0;
    const cogs = Number(item.unit_cost) * qty + feeShare;
    return { revenue, net: revenue - fees - cogs };
  }, [form, item]);

  if (!item || !form) return null;

  function validate() {
    const next = {};
    const qty = Number(form.quantity_sold);
    if (!form.marketplace_id) next.marketplace_id = "Where did it sell?";
    if (!(qty > 0)) next.quantity_sold = "Must be at least 1.";
    else if (qty > item.quantity_remaining)
      next.quantity_sold = `Only ${item.quantity_remaining} left in this lot.`;
    if (form.unit_price === "" || Number(form.unit_price) < 0)
      next.unit_price = "Enter the sale price per unit.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      await api.createSale({
        item_id: item.id,
        marketplace_id: Number(form.marketplace_id),
        quantity_sold: Number(form.quantity_sold),
        unit_price: form.unit_price,
        platform_fee: form.platform_fee || "0",
        shipping_cost: form.shipping_cost || "0",
        sold_at: new Date(form.sold_at).toISOString(),
      });
      onLogged();
      onClose();
    } catch (err) {
      // A 409 here means the lot ran out between opening this form and
      // submitting it — the server's oversell guard, surfaced verbatim.
      setErrors({
        form: err instanceof ApiError ? err.fieldMessage : "Could not reach the server.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Log a sale"
      description={`${item.name}${item.size ? ` · size ${item.size}` : ""} — ${item.quantity_remaining} of ${item.quantity} left`}
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <Field id="marketplace_id" label="Marketplace" error={errors.marketplace_id}>
          <select
            id="marketplace_id"
            value={form.marketplace_id}
            onChange={onMarketplaceChange}
            className={fieldClass}
          >
            <option value="">Choose a marketplace</option>
            {marketplaces.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field
            id="quantity_sold"
            label="Units sold"
            type="number"
            min="1"
            max={item.quantity_remaining}
            step="1"
            value={form.quantity_sold}
            onChange={set("quantity_sold")}
            error={errors.quantity_sold}
          />
          <Field
            id="unit_price"
            label="Sale price per unit"
            type="number"
            min="0"
            step="0.01"
            prefix="$"
            placeholder="310.00"
            value={form.unit_price}
            onChange={set("unit_price")}
            error={errors.unit_price}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Field
            id="platform_fee"
            label="Platform fee"
            type="number"
            min="0"
            step="0.01"
            prefix="$"
            placeholder="0.00"
            value={form.platform_fee}
            onChange={set("platform_fee")}
          />
          <Field
            id="shipping_cost"
            label="Shipping you paid"
            type="number"
            min="0"
            step="0.01"
            prefix="$"
            placeholder="0.00"
            value={form.shipping_cost}
            onChange={set("shipping_cost")}
          />
        </div>

        <Field
          id="sold_at"
          label="Sale date"
          type="datetime-local"
          value={form.sold_at}
          onChange={set("sold_at")}
        />

        {preview && preview.revenue > 0 && (
          <div className="flex items-baseline justify-between rounded-lg bg-surface px-3 py-2.5">
            <span className="text-sm text-muted">Net profit on this sale</span>
            <Profit value={preview.net} />
          </div>
        )}

        {errors.form && (
          <p role="alert" className="text-sm text-loss">
            {errors.form}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button onClick={onClose} type="button">
            Cancel
          </Button>
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? "Logging" : "Log sale"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
