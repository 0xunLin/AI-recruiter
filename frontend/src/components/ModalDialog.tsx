import { useEffect, useId, useRef, type ReactNode } from "react";

interface ModalDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  maxWidthClass?: string;
  children: ReactNode;
}

export function ModalDialog({
  open,
  onClose,
  title,
  subtitle,
  maxWidthClass = "max-w-2xl",
  children,
}: ModalDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;

    let pressedOutside = false;
    const isOutside = (e: PointerEvent) => {
      const r = dialog.getBoundingClientRect();
      return (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      );
    };

    const onDown = (e: PointerEvent) => {
      pressedOutside = isOutside(e);
    };
    const onUp = (e: PointerEvent) => {
      if (pressedOutside && isOutside(e)) {
        dialog.close();
      }
      pressedOutside = false;
    };

    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, []);

  const handleClose = () => {
    if (dialogRef.current) {
      dialogRef.current.returnValue = "";
    }
    onClose();
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={titleId}
      onClose={handleClose}
      {...({ closedby: "any" } as Record<string, string>)}
      className={`w-[calc(100%-2rem)] ${maxWidthClass} p-0`}
    >
      <div className="flex items-start justify-between gap-4 border-b-2 border-[var(--border-heavy)] px-6 py-4">
        <div>
          <h1 id={titleId} className="display-heading text-base font-bold text-[var(--ink-primary)]">
            {title}
          </h1>
          {subtitle && (
            <p className="editorial-note mt-1 text-xs text-[var(--ink-muted)]">{subtitle}</p>
          )}
        </div>
        <button
          type="button"
          onClick={() => dialogRef.current?.close()}
          aria-label={`Close ${title}`}
          className="wire-btn h-8 px-3 text-[11px] uppercase tracking-[0.06em]"
        >
          Close
        </button>
      </div>
      <div className="overflow-y-auto p-6">{children}</div>
    </dialog>
  );
}
