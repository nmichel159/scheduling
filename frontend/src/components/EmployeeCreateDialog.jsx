import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { CloseIcon } from './NavIcons';

/**
 * Small modal for creating a new account on the shown workplace; it is mounted per opening so the form starts empty: given
 * name, family name, titles and e-mail. The account is matched on its e-mail at
 * the person's first sign-in, so nothing else is asked here.
 *
 * Props:
 * - saving: boolean — disables the form while the request is in flight
 * - error: string | null — why the last attempt failed
 * - onCreate({ title_before, first_name, last_name, title_after, email })
 * - onClose()
 */
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const EmployeeCreateDialog = ({ saving = false, error = null, onCreate, onClose }) => {
  const { t } = useTranslation();
  const titleId = useId();
  const firstRef = useRef(null);
  const [form, setForm] = useState({ before: '', first: '', last: '', after: '', email: '' });

  useEffect(() => {
    firstRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const valid =
    form.first.trim() !== '' &&
    form.last.trim() !== '' &&
    EMAIL_PATTERN.test(form.email.trim());

  const submit = (e) => {
    e.preventDefault();
    if (!valid || saving) return;
    onCreate({
      title_before: form.before.trim(),
      first_name: form.first.trim(),
      last_name: form.last.trim(),
      title_after: form.after.trim(),
      email: form.email.trim(),
    });
  };

  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }));

  return createPortal(
    <div
      className="dialog-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={submit}
      >
        <header className="dialog-header">
          <h2 id={titleId} className="dialog-title">
            {t('employees.new_account_title')}
          </h2>
          <button
            type="button"
            className="dialog-close"
            onClick={onClose}
            aria-label={t('employees.cancel')}
          >
            <CloseIcon />
          </button>
        </header>

        <div
          className="dialog-body"
          style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}
        >
          <div className="field">
            <label className="field-label" htmlFor={`${titleId}-before`}>
              {t('employees.title_before')}
            </label>
            <input
              id={`${titleId}-before`}
              className="input"
              value={form.before}
              disabled={saving}
              onChange={set('before')}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={`${titleId}-after`}>
              {t('employees.title_after')}
            </label>
            <input
              id={`${titleId}-after`}
              className="input"
              value={form.after}
              disabled={saving}
              onChange={set('after')}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={`${titleId}-first`}>
              {t('competences.first_name')}
            </label>
            <input
              id={`${titleId}-first`}
              ref={firstRef}
              className="input"
              value={form.first}
              disabled={saving}
              onChange={set('first')}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={`${titleId}-last`}>
              {t('competences.last_name')}
            </label>
            <input
              id={`${titleId}-last`}
              className="input"
              value={form.last}
              disabled={saving}
              onChange={set('last')}
            />
          </div>
          <div className="field" style={{ gridColumn: '1 / -1' }}>
            <label className="field-label" htmlFor={`${titleId}-email`}>
              {t('competences.email')}
            </label>
            <input
              id={`${titleId}-email`}
              className="input"
              type="email"
              value={form.email}
              disabled={saving}
              onChange={set('email')}
            />
          </div>
        </div>

        {error && (
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        )}

        <div className="dialog-footer">
          <button type="button" className="btn" onClick={onClose}>
            {t('employees.cancel')}
          </button>
          <button type="submit" className="btn btn-primary" disabled={!valid || saving}>
            {t('employees.create_account')}
          </button>
        </div>
      </form>
    </div>,
    document.body
  );
};

export default EmployeeCreateDialog;
