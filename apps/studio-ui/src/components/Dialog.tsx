import type { ReactNode } from "react";
import { Dialog as AriaDialog, Heading, Modal, ModalOverlay } from "react-aria-components";

interface DialogProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  role?: "dialog" | "alertdialog";
  dismissable?: boolean;
  wide?: boolean;
}

/** Accessible modal (focus trap, Escape, focus restore) built on React Aria. */
export function Dialog({
  isOpen,
  onClose,
  title,
  children,
  role = "dialog",
  dismissable = true,
  wide = false,
}: DialogProps) {
  return (
    <ModalOverlay
      className="modal-overlay"
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      isDismissable={dismissable}
      isKeyboardDismissDisabled={!dismissable}
    >
      <Modal className={wide ? "modal modal-wide" : "modal"}>
        <AriaDialog role={role} aria-label={title} style={{ outline: "none" }}>
          <Heading slot="title">{title}</Heading>
          {children}
        </AriaDialog>
      </Modal>
    </ModalOverlay>
  );
}

interface ConfirmProps {
  isOpen: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  isOpen,
  title,
  body,
  confirmLabel,
  cancelLabel = "Cancel",
  danger,
  busy,
  onConfirm,
  onCancel,
}: ConfirmProps) {
  return (
    <Dialog isOpen={isOpen} onClose={onCancel} title={title} role="alertdialog">
      <p>{body}</p>
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onCancel}>
          {cancelLabel}
        </button>
        <button
          type="button"
          className={danger ? "btn btn-danger" : "btn btn-primary"}
          onClick={onConfirm}
          disabled={busy}
        >
          {confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
