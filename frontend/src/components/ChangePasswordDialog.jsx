import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { changePassword, passwordErrorMessage } from '../services/authService';
import { CloseIcon } from './NavIcons';

const EMPTY = { current: '', next: '', confirm: '' };

/** Zmena vlastného hesla. Otvára sa z menu pod menom v bočnej lište. */
const ChangePasswordDialog = ({ open, onClose, onChanged }) => {
  const { t } = useTranslation();
  const titleId = useId();
  const firstRef = useRef(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return undefined;
    setForm(EMPTY);
    setError('');
    firstRef.current?.focus();
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const valid = form.current && form.next && form.confirm;

  const submit = async (e) => {
    e.preventDefault();
    if (form.next !== form.confirm) {
      setError(t('password.mismatch'));
      return;
    }
    setSaving(true);
    setError('');
    try {
      await changePassword(form.current, form.next);
      onChanged?.();
      onClose();
    } catch (err) {
      setError(passwordErrorMessage(t, err));
    } finally {
      setSaving(false);
    }
  };

  const fields = [
    { key: 'current', label: t('password.current'), autoComplete: 'current-password' },
    { key: 'next', label: t('password.new'), autoComplete: 'new-password' },
    { key: 'confirm', label: t('password.confirm'), autoComplete: 'new-password' },
  ];

  return createPortal(
    <div
      className="dialog-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        className="dialog dialog-sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={submit}
      >
        <header className="dialog-header">
          <h2 id={titleId} className="dialog-title">
            {t('password.change_title')}
          </h2>
          <button
            type="button"
            className="dialog-close"
            onClick={onClose}
            aria-label={t('password.cancel')}
          >
            <CloseIcon className="" />
          </button>
        </header>

        <div className="dialog-body" style={{ display: 'grid', gap: 10 }}>
          {fields.map((field, index) => (
            <div className="field" key={field.key}>
              <label className="field-label" htmlFor={`${titleId}-${field.key}`}>
                {field.label}
              </label>
              <input
                id={`${titleId}-${field.key}`}
                ref={index === 0 ? firstRef : undefined}
                className="input"
                type="password"
                autoComplete={field.autoComplete}
                value={form[field.key]}
                disabled={saving}
                onChange={set(field.key)}
              />
            </div>
          ))}
        </div>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        <div className="dialog-footer">
          <button type="button" className="btn" onClick={onClose}>
            {t('password.cancel')}
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || saving}>
            {t('password.save')}
          </button>
        </div>
      </form>
    </div>,
    document.body
  );
};

export default ChangePasswordDialog;
