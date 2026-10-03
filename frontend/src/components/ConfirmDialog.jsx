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
 * - hideCancel: a notice rather than a question -- one button, which both
 *   confirms and dismisses (Escape and a click outside call onCancel)
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
  hideCancel = false,
  onConfirm,
  onCancel,
}) => {
  const confirmBtnRef = useRef(null);
  const onCancelRef = useRef(onCancel);
  const messageId = useId();

  // Callers pass inline callbacks; holding the latest one in a ref keeps the
  // effect below from re-running (and re-focusing the button) on every render.
  useEffect(() => {
    onCancelRef.current = onCancel;
  }, [onCancel]);

  useEffect(() => {
    if (!open) return;
    confirmBtnRef.current?.focus();

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onCancelRef.current?.();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);

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
          {!hideCancel && (
            <button type="button" className="btn" onClick={onCancel}>
              {cancelLabel}
            </button>
          )}
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
