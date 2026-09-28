import { useId, useLayoutEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { SHIFT_PREFERENCE } from '../services/employeeService';
import { personInitials } from '../utils/personInitials';
import { CheckIcon, CloseIcon, PlusIcon } from './NavIcons';
import './EmployeeDetailDialog.css';

/**
 * Profile of one employee, shown as a centered modal.
 *
 * It prints the basics on every screen that opens it, and grows an edit
 * form on the screens that pass `settings`: the scheduler's employees view
 * hands over the duty wish and the duty-kind preference, the competence
 * matrix does not and keeps the read-only card it always had.
 *
 * When `allCompetences` is given as well, the competence section stops
 * being a list of names and becomes the place where they are assigned —
 * every competence of the workplace is a toggle, the ones the person
 * holds are on. Nothing leaves the dialog until Save: competences and
 * preferences go together, so closing a half-finished edit changes
 * nothing.
 *
 * The backend keeps one `full_name`; it is split into given/family name
 * here the way an edit form will collect it.
 *
 * Props:
 * - employee: { user_id, full_name, email } | null — null renders nothing
 * - competences: [{ id, name }] — the ones the employee holds
 * - allCompetences: [{ id, name }] — the workplace's whole codebook;
 *   passing it (together with `settings`) makes the section editable
 * - settings: { max_shifts_per_month, shift_preference } | null — when
 *   given, the dialog becomes an edit form
 * - stats: the shown month's counts — duties, hours, weekends, the
 *   longest run of consecutive days, and how the person filled their
 *   availability calendar; null hides both number sections
 * - days: [{ work_date, competence_id, competence_name, is_surcharge }]
 * - monthLabel: string — which month `days` and `stats` describe
 * - daysInMonth: number — how many days that month has, the denominator
 *   of the filled-in availability count
 * - formatDay(day) — how one duty's date is printed
 * - saving: boolean — disables the form while a save is in flight
 * - error: string | null — why the last save failed; shown above the
 *   buttons, the form keeps what was typed
 * - onSave({ max_shifts_per_month, shift_preference, competence_ids })
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

/* What the stepper's buttons and the number input agree on — and what the
 * backend accepts (0..31, whole numbers). */
const MAX_SHIFTS_LIMIT = 31;

/** A typed wish as the API takes it: null for "no opinion", otherwise a
 *  whole number inside the limit. Typing 40 or 2.5 must not end in a 422. */
const clampShifts = (text) => {
  const trimmed = String(text).trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return null;
  return Math.min(MAX_SHIFTS_LIMIT, Math.max(0, Math.round(value)));
};

/** One number with its label; the dialog prints a grid of them. */
const Tile = ({ label, value, accent = false }) => (
  <div className={`empdlg-tile ${accent ? 'is-accent' : ''}`}>
    <span className="empdlg-tile-value">{value}</span>
    <span className="empdlg-tile-label">{label}</span>
  </div>
);

const EmployeeDetailDialog = ({
  employee,
  competences = [],
  allCompetences = null,
  settings = null,
  stats = null,
  days = [],
  monthLabel = '',
  daysInMonth = 0,
  formatDay = (d) => d.work_date,
  saving = false,
  error = null,
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
  const [picked, setPicked] = useState(() => competences.map((c) => c.id));
  const titleId = useId();

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
  const editableCompetences = editable && Array.isArray(allCompetences);

  /** Step the duty wish, treating "no opinion" as the current count. */
  const stepShifts = (delta) => {
    const current = clampShifts(maxShifts) ?? 0;
    const next = Math.min(MAX_SHIFTS_LIMIT, Math.max(0, current + delta));
    setMaxShifts(String(next));
  };

  /** Leaving the field shows the number that will actually be saved. */
  const commitShifts = () => {
    const value = clampShifts(maxShifts);
    setMaxShifts(value == null ? '' : String(value));
  };

  const toggleCompetence = (id) => {
    setPicked((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSave = () => {
    onSave({
      max_shifts_per_month: clampShifts(maxShifts),
      shift_preference: preference,
      competence_ids: editableCompetences ? picked : competences.map((c) => c.id),
    });
  };

  return createPortal(
    <div
      className="dialog-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="dialog empdlg"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="dialog-header empdlg-head">
          <div className="empdlg-avatar" aria-hidden="true">
            {personInitials(label)}
          </div>
          <div className="empdlg-heading">
            <h2 id={titleId} className="dialog-title empdlg-title">
              {label}
            </h2>
            {employee.full_name && (
              <p className="dialog-description empdlg-subtitle">{employee.email}</p>
            )}
          </div>
          <button
            type="button"
            className="dialog-close"
            onClick={onClose}
            title={t('competences.close_detail')}
            aria-label={t('competences.close_detail')}
          >
            <CloseIcon />
          </button>
        </header>

        <div className="dialog-body empdlg-body">
          <section className="empdlg-section">
            <h3 className="empdlg-section-title">
              {t('competences.employee_detail')}
            </h3>
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
            </dl>
          </section>

          <section className="empdlg-section">
            <h3 className="empdlg-section-title">
              {t('competences.title')}
              {editableCompetences && (
                <span className="empdlg-section-count">
                  {picked.length} / {allCompetences.length}
                </span>
              )}
            </h3>

            {editableCompetences ? (
              allCompetences.length === 0 ? (
                <p className="empdlg-none">{t('competences.empty')}</p>
              ) : (
                <div className="empdlg-chips">
                  {allCompetences.map((c) => {
                    const on = picked.includes(c.id);
                    return (
                      <button
                        key={c.id}
                        type="button"
                        className={`empdlg-chip ${on ? 'is-on' : ''}`.trim()}
                        aria-pressed={on}
                        disabled={saving}
                        onClick={() => toggleCompetence(c.id)}
                      >
                        {on ? (
                          <CheckIcon className="empdlg-chip-mark" />
                        ) : (
                          <PlusIcon className="empdlg-chip-mark" />
                        )}
                        {c.name}
                      </button>
                    );
                  })}
                </div>
              )
            ) : (
              <p className="empdlg-none">
                {competences.map((c) => c.name).join(', ') || '—'}
              </p>
            )}
          </section>

          {editable && (
            <section className="empdlg-section">
              <h3 className="empdlg-section-title">{t('employees.settings')}</h3>

              <div className="field empdlg-field">
                <label className="field-label" htmlFor={`${titleId}-max`}>
                  {t('employees.max_shifts')}
                </label>
                <div className="empdlg-stepper">
                  <button
                    type="button"
                    className="btn btn-icon"
                    onClick={() => stepShifts(-1)}
                    disabled={saving || maxShifts.trim() === '0'}
                    aria-label={t('employees.decrease')}
                    title={t('employees.decrease')}
                  >
                    −
                  </button>
                  <input
                    id={`${titleId}-max`}
                    type="number"
                    min="0"
                    max={MAX_SHIFTS_LIMIT}
                    step="1"
                    inputMode="numeric"
                    className="input empdlg-input"
                    value={maxShifts}
                    disabled={saving}
                    placeholder="—"
                    onChange={(e) => setMaxShifts(e.target.value)}
                    onBlur={commitShifts}
                  />
                  <button
                    type="button"
                    className="btn btn-icon"
                    onClick={() => stepShifts(1)}
                    disabled={saving || clampShifts(maxShifts) === MAX_SHIFTS_LIMIT}
                    aria-label={t('employees.increase')}
                    title={t('employees.increase')}
                  >
                    +
                  </button>
                  {maxShifts.trim() !== '' && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm empdlg-clear"
                      onClick={() => setMaxShifts('')}
                      disabled={saving}
                    >
                      {t('employees.no_limit')}
                    </button>
                  )}
                </div>
              </div>

              <div className="field empdlg-field">
                <span className="field-label" id={`${titleId}-pref`}>
                  {t('employees.preference')}
                </span>
                <div
                  className="segmented empdlg-choice"
                  role="group"
                  aria-labelledby={`${titleId}-pref`}
                >
                  {PREFERENCE_ORDER.map((value) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={preference === value}
                      disabled={saving}
                      onClick={() => setPreference(value)}
                    >
                      {t(`employees.preference_${value}`)}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          )}

          {stats && (
            <>
              <section className="empdlg-section">
                <h3 className="empdlg-section-title">
                  {monthLabel}
                  <span className="empdlg-section-count">
                    {t(`employees.preference_${stats.preference}`)}
                  </span>
                </h3>

                <div className="empdlg-tiles">
                  <Tile
                    label={t('employees.stat_shifts')}
                    value={
                      stats.max != null ? `${stats.shifts}/${stats.max}` : stats.shifts
                    }
                  />
                  <Tile
                    label={t('employees.stat_surcharge')}
                    value={stats.surcharge}
                    accent={stats.surcharge > 0}
                  />
                  <Tile label={t('employees.stat_standard')} value={stats.standard} />
                  <Tile label={t('employees.stat_weekend')} value={stats.weekend} />
                  <Tile label={t('employees.stat_hours')} value={stats.hours} />
                  <Tile label={t('employees.stat_avg_hours')} value={stats.avgHours} />
                  <Tile
                    label={t('employees.stat_free')}
                    value={stats.free == null ? '—' : stats.free}
                    accent={stats.free != null && stats.free < 0}
                  />
                  <Tile label={t('employees.stat_streak')} value={stats.streak} />
                  <Tile
                    label={t('competences.title')}
                    value={editableCompetences ? picked.length : competences.length}
                  />
                </div>

                {days.length === 0 ? (
                  <p className="empdlg-none">{t('employees.no_shifts')}</p>
                ) : (
                  <div className="empdlg-days">
                    {days.map((d) => (
                      <span
                        key={`${d.work_date}-${d.competence_id}`}
                        className={`empdlg-day ${d.is_surcharge ? 'is-surcharge' : ''}`.trim()}
                        title={d.competence_name || ''}
                      >
                        {formatDay(d)}
                      </span>
                    ))}
                  </div>
                )}
              </section>

              {/* What the person said about the month before it was
                * planned — the counts the availability calendar holds. */}
              <section className="empdlg-section">
                <h3 className="empdlg-section-title">
                  {t('employees.availability')}
                  <span className="empdlg-section-count">
                    {stats.marked} / {daysInMonth}
                  </span>
                </h3>
                <div className="empdlg-tiles">
                  <Tile label={t('employees.stat_marked')} value={stats.marked} />
                  <Tile label={t('employees.stat_preferred')} value={stats.preferred} />
                  <Tile label={t('employees.stat_declined')} value={stats.declined} />
                  <Tile
                    label={t('employees.stat_blocked')}
                    value={stats.blocked}
                    accent={stats.blocked > 0}
                  />
                </div>
              </section>
            </>
          )}
        </div>

        {error && (
          <div className="alert alert-danger empdlg-error" role="alert">
            {error}
          </div>
        )}

        <div className="dialog-footer">
          <button type="button" className="btn" onClick={onClose}>
            {t('competences.close_detail')}
          </button>
          {editable && (
            <button
              type="button"
              className="btn btn-primary"
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
