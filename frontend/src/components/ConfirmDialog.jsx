import { useEffect, useRef } from 'react';
import './ConfirmDialog.css';

/**
 * Generic app-styled confirm dialog, replacing window.confirm.
 *
 * Props:
 * - open: whether to render the dialog
 * - message: body text
 * - confirmLabel / cancelLabel: button labels
 * - onConfirm / onCancel: callbacks
 */
const ConfirmDialog = ({ open, message, confirmLabel, cancelLabel, onConfirm, onCancel }) => {
  const confirmBtnRef = useRef(null);

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
      className="confirm-dialog-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="confirm-dialog" role="dialog" aria-modal="true">
        <p className="confirm-dialog-message">{message}</p>
        <div className="confirm-dialog-actions">
          <button type="button" className="departments-btn" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmBtnRef}
            className="departments-btn departments-btn-primary"
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
