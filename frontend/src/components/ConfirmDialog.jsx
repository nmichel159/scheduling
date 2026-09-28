import { useEffect, useId, useRef } from 'react';
import './ConfirmDialog.css';

/**
 * Generic app-styled confirm dialog, replacing window.confirm.
 *
 * Props:
 * - open: whether to render the dialog
 * - title: optional heading above the message
 * - message: body text
 * - details: optional secondary line under the message (e.g. an estimate)
 * - confirmLabel / cancelLabel: button labels
 * - tone: 'primary' (default) or 'danger' for destructive actions
 * - onConfirm / onCancel: callbacks
 */
const ConfirmDialog = ({
  open,
  title,
  message,
  details,
  confirmLabel,
  cancelLabel,
  tone = 'primary',
  onConfirm,
  onCancel,
}) => {
  const confirmBtnRef = useRef(null);
  const messageId = useId();

  useEffect(() => {
    if (!open) return;
    confirmBtnRef.current?.focus();

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="dialog-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        className="dialog dialog-sm confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-describedby={messageId}
      >
        <div className="dialog-body confirm-dialog-body">
          {title && <h2 className="dialog-title confirm-dialog-title">{title}</h2>}
          <p id={messageId} className="confirm-dialog-message">{message}</p>
          {details && <p className="confirm-dialog-details">{details}</p>}
        </div>
        <div className="dialog-footer">
          <button type="button" className="btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmBtnRef}
            className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-primary'}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfirmDialog;
