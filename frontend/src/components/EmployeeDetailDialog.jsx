import { useLayoutEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { SHIFT_PREFERENCE } from '../services/employeeService';
import './EmployeeDetailDialog.css';

/**
 * Card of one employee, shown as a centered modal.
 *
 * It prints the basics on every screen that opens it, and grows an edit
 * form on the screens that pass `settings`: the scheduler's employees view
 * hands over the duty wish and the duty-kind preference, the competence
 * matrix does not and keeps the read-only card it always had.
 *
 * The backend keeps one `full_name`; it is split into given/family name
 * here the way an edit form will collect it.
 *
 * Props:
 * - employee: { user_id, full_name, email } | null — null renders nothing
 * - competences: [{ id, name }] — names to print under "Kompetencie";
 *   pass the ones the employee actually holds, already filtered
 * - settings: { max_shifts_per_month, shift_preference } | null — when
 *   given, the dialog becomes an edit form for these two fields
 * - saving: boolean — disables the form while a save is in flight
 * - onSave(settings) — called with the edited settings
 * - onClose()
 */
const splitName = (fullName) => {
  const parts = (fullName || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { first: '', last: '' };
  return { first: parts[0], last: parts.slice(1).join(' ') };
};

const PREFERENCE_ORDER = [
  SHIFT_PREFERENCE.SURCHARGE,
  SHIFT_PREFERENCE.STANDARD,
  SHIFT_PREFERENCE.ANY,
];

const EmployeeDetailDialog = ({
  employee,
  competences = [],
  settings = null,
  saving = false,
  onSave,
  onClose,
}) => {
  const { t } = useTranslation();

  /* An empty string is a third state the number input needs and the API
   * does not have: it is what "no opinion" looks like while typing, and
   * it is sent as null.
   *
   * The form is seeded once per mount rather than synced from `settings`:
   * the opening screen gives the dialog a key per employee, so switching
   * people remounts it and nothing has to be reset by hand. */
  const [maxShifts, setMaxShifts] = useState(() =>
    settings && settings.max_shifts_per_month != null
      ? String(settings.max_shifts_per_month)
      : ''
  );
  const [preference, setPreference] = useState(
    () => (settings && settings.shift_preference) || SHIFT_PREFERENCE.ANY
  );

  useLayoutEffect(() => {
    if (!employee) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [employee, onClose]);

  if (!employee) return null;

  const name = splitName(employee.full_name);
  const label = employee.full_name || employee.email;
  const editable = settings != null && typeof onSave === 'function';

  const handleSave = () => {
    const trimmed = maxShifts.trim();
    onSave({
      max_shifts_per_month: trimmed === '' ? null : Number(trimmed),
      shift_preference: preference,
    });
  };

  return createPortal(
    <div
      className="empdlg-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="empdlg" role="dialog" aria-modal="true">
        <header className="empdlg-head">
          <div className="empdlg-avatar" aria-hidden="true">
            {label.trim().charAt(0).toUpperCase()}
          </div>
          <div className="empdlg-heading">
            <h3 className="empdlg-title">{label}</h3>
            <p className="empdlg-subtitle">{t('competences.employee_detail')}</p>
          </div>
          <button
            type="button"
            className="empdlg-close"
            onClick={onClose}
            title={t('departments.cancel')}
            aria-label={t('departments.cancel')}
          >
            ✕
          </button>
        </header>

        <dl className="empdlg-fields">
          <div>
            <dt>{t('competences.first_name')}</dt>
            <dd>{name.first || '—'}</dd>
          </div>
          <div>
            <dt>{t('competences.last_name')}</dt>
            <dd>{name.last || '—'}</dd>
          </div>
          <div>
            <dt>{t('competences.email')}</dt>
            <dd>{employee.email}</dd>
          </div>
          <div>
            <dt>{t('competences.title')}</dt>
            <dd>{competences.map((c) => c.name).join(', ') || '—'}</dd>
          </div>
        </dl>

        {editable ? (
          <div className="empdlg-form">
            <label className="empdlg-field">
              <span className="empdlg-label">{t('employees.max_shifts')}</span>
              <input
                type="number"
                min="0"
                max="31"
                inputMode="numeric"
                className="empdlg-input"
                value={maxShifts}
                disabled={saving}
                placeholder="—"
                onChange={(e) => setMaxShifts(e.target.value)}
              />
            </label>

            <div className="empdlg-field">
              <span className="empdlg-label">{t('employees.preference')}</span>
              <div
                className="empdlg-choice"
                role="group"
                aria-label={t('employees.preference')}
              >
                {PREFERENCE_ORDER.map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={`empdlg-choice-button ${
                      preference === value ? 'is-active' : ''
                    }`}
                    aria-pressed={preference === value}
                    disabled={saving}
                    onClick={() => setPreference(value)}
                  >
                    {t(`employees.preference_${value}`)}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <p className="empdlg-note">{t('competences.detail_readonly')}</p>
        )}

        <div className="empdlg-actions">
          <button type="button" className="departments-btn" onClick={onClose}>
            {t('competences.close_detail')}
          </button>
          {editable && (
            <button
              type="button"
              className="departments-btn departments-btn-primary"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? t('employees.saving') : t('employees.save')}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};

export default EmployeeDetailDialog;
