import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import type { TicketStatus } from "./supportTypes";
export const statusLabel: Record<TicketStatus, string> = {
  open: "Open",
  queued: "Queued",
  processing: "Processing",
  review: "Needs review",
  approved: "Approved",
  escalated: "Escalated",
  failed: "Failed",
  cancelled: "Cancelled",
};
export function TicketBadge({ status }: { status: TicketStatus }) {
  return (
    <span className={`sd-badge sd-status-${status}`}>
      {statusLabel[status]}
    </span>
  );
}
export function supportDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Unrecorded"
    : date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}
export function SupportDialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="sd-dialog"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      aria-label={title}
    >
      <div className="sd-dialog-head">
        <h2>{title}</h2>
        <button className="sd-icon" aria-label="Close dialog" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
