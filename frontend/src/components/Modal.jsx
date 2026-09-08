import { useEffect, useRef } from "react";
import { X } from "lucide-react";

/**
 * Dialog built on <dialog>, which gives focus trapping, Escape-to-close, and
 * the top layer without reimplementing any of it in JS.
 */
export default function Modal({ open, onClose, title, description, children }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // showModal() is what makes it modal; the open attribute alone does not.
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      // Clicking the backdrop hits the dialog element itself, not its contents.
      onClick={(e) => e.target === ref.current && onClose()}
      className="m-auto w-[min(34rem,calc(100vw-2rem))] rounded-xl bg-ground p-0 text-ink shadow-2xl backdrop:bg-black/40"
    >
      <div className="flex items-start gap-4 border-b border-line px-5 py-4">
        <div className="flex-1">
          <h2 className="expanded font-semibold">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="grid size-8 shrink-0 place-items-center rounded-lg text-muted hover:bg-surface hover:text-ink"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div className="px-5 py-5">{children}</div>
    </dialog>
  );
}
