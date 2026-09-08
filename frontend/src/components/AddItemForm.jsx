import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { Button } from "./ui";
import Field, { fieldClass } from "./Field";
import Modal from "./Modal";

const CONDITIONS = [
  { value: "new", label: "New" },
  { value: "like_new", label: "Like new" },
  { value: "used", label: "Used" },
  { value: "damaged", label: "Damaged" },
];

const today = () => new Date().toISOString().slice(0, 10);

const EMPTY = {
  name: "",
  size: "",
  condition: "new",
  quantity: "1",
  unit_cost: "",
  acquisition_fee_total: "",
  purchased_at: today(),
  source: "",
  notes: "",
};

export default function AddItemForm({ open, onClose, onCreated }) {
  const [form, setForm] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function validate() {
    const next = {};
    if (!form.name.trim()) next.name = "Give the item a name.";
    if (!(Number(form.quantity) > 0)) next.quantity = "Must be at least 1.";
    if (form.unit_cost === "" || Number(form.unit_cost) < 0)
      next.unit_cost = "Enter what you paid per unit.";
    if (!form.purchased_at) next.purchased_at = "When did you buy it?";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!validate()) return;
    setBusy(true);
    try {
      const created = await api.createItem({
        name: form.name.trim(),
        // Empty optional fields are sent as null rather than "", which the API
        // would store as a real empty string.
        size: form.size.trim() || null,
        condition: form.condition,
        quantity: Number(form.quantity),
        unit_cost: form.unit_cost,
        acquisition_fee_total: form.acquisition_fee_total || "0",
        purchased_at: form.purchased_at,
        source: form.source.trim() || null,
        notes: form.notes.trim() || null,
      });
      setForm(EMPTY);
      setErrors({});
      onCreated(created);
      onClose();
    } catch (err) {
      setErrors({
        form: err instanceof ApiError ? err.fieldMessage : "Could not reach the server.",
      });
    } finally {
      setBusy(false);
    }
  }

  const total =
    (Number(form.unit_cost) || 0) * (Number(form.quantity) || 0) +
    (Number(form.acquisition_fee_total) || 0);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add inventory"
      description="One row is a lot: several identical units bought together at the same price."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          id="name"
          label="Item"
          placeholder="Jordan 4 Retro Bred"
          value={form.name}
          onChange={set("name")}
          error={errors.name}
          autoFocus
        />

        <div className="grid grid-cols-2 gap-4">
          <Field
            id="size"
            label="Size"
            placeholder="10.5"
            value={form.size}
            onChange={set("size")}
          />
          <Field id="condition" label="Condition">
            <select
              id="condition"
              value={form.condition}
              onChange={set("condition")}
              className={fieldClass}
            >
              {CONDITIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Field
            id="quantity"
            label="Units"
            type="number"
            min="1"
            step="1"
            value={form.quantity}
            onChange={set("quantity")}
            error={errors.quantity}
          />
          <Field
            id="unit_cost"
            label="Cost per unit"
            type="number"
            min="0"
            step="0.01"
            prefix="$"
            placeholder="180.00"
            value={form.unit_cost}
            onChange={set("unit_cost")}
            error={errors.unit_cost}
          />
        </div>

        <Field
          id="acquisition_fee_total"
          label="Purchase fees"
          type="number"
          min="0"
          step="0.01"
          prefix="$"
          placeholder="0.00"
          value={form.acquisition_fee_total}
          onChange={set("acquisition_fee_total")}
          hint="Shipping or fees for the whole purchase, not per unit. Split across sales automatically."
        />

        <div className="grid grid-cols-2 gap-4">
          <Field
            id="purchased_at"
            label="Bought on"
            type="date"
            value={form.purchased_at}
            onChange={set("purchased_at")}
            error={errors.purchased_at}
          />
          <Field
            id="source"
            label="Bought from"
            placeholder="SNKRS"
            value={form.source}
            onChange={set("source")}
          />
        </div>

        {total > 0 && (
          <p className="text-sm text-muted">
            Total outlay{" "}
            <span className="tabular font-medium text-ink">${total.toFixed(2)}</span>
          </p>
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
          {/* The button names the outcome, and the toast will say "Added". */}
          <Button variant="primary" type="submit" disabled={busy}>
            {busy ? "Adding" : "Add to inventory"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
