import { useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import './EmployeeDetailDialog.css';

/**
 * Read-only card of one employee, shown as a centered modal.
 *
 * It is deliberately a modal and not another little popover: today it only
 * prints the basics, but this is where editing the person (name, e-mail,
 * phone, …) is going to live, and a form needs the room. Both screens that
 * show a list of people — the competence matrix and the employees view —
 * open this same dialog, so that future form only has to be built once.
 *
 * The backend keeps one `full_name`; it is split into given/family name
 * here the way an edit form will collect it.
 *
 * Props:
 * - employee: { user_id, full_name, email } | null — null renders nothing
 * - competences: [{ id, name }] — names to print under "Kompetencie";
 *   pass the ones the employee actually holds, already filtered
 * - onClose()
 */
const splitName = (fullName) => {
  const parts = (fullName || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { first: '', last: '' };
  return { first: parts[0], last: parts.slice(1).join(' ') };
};

const EmployeeDetailDialog = ({ employee, competences = [], onClose }) => {
  const { t } = useTranslation();

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

        <p className="empdlg-note">{t('competences.detail_readonly')}</p>

        <div className="empdlg-actions">
          <button type="button" className="departments-btn" onClick={onClose}>
            {t('competences.close_detail')}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default EmployeeDetailDialog;
