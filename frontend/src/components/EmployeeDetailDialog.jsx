import { useLayoutEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { SHIFT_PREFERENCE } from '../services/employeeService';
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

/* What the stepper's buttons and the number input agree on. */
const MAX_SHIFTS_LIMIT = 31;

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
    const current = maxShifts.trim() === '' ? 0 : Number(maxShifts);
    const next = Math.min(MAX_SHIFTS_LIMIT, Math.max(0, current + delta));
    setMaxShifts(String(next));
  };

  const toggleCompetence = (id) => {
    setPicked((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handleSave = () => {
    const trimmed = maxShifts.trim();
    onSave({
      max_shifts_per_month: trimmed === '' ? null : Number(trimmed),
      shift_preference: preference,
      competence_ids: editableCompetences ? picked : competences.map((c) => c.id),
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
            <p className="empdlg-subtitle">{employee.email}</p>
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

        <div className="empdlg-body">
          <section className="empdlg-section">
            <h4 className="empdlg-section-title">
              {t('competences.employee_detail')}
            </h4>
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
            <h4 className="empdlg-section-title">
              {t('competences.title')}
              {editableCompetences && (
                <span className="empdlg-section-count">
                  {picked.length} / {allCompetences.length}
                </span>
              )}
            </h4>

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
                        className={`empdlg-chip ${on ? 'is-on' : ''}`}
                        aria-pressed={on}
                        disabled={saving}
                        onClick={() => toggleCompetence(c.id)}
                      >
                        <span className="empdlg-chip-mark" aria-hidden="true">
                          {on ? '✓' : '+'}
                        </span>
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
              <h4 className="empdlg-section-title">{t('employees.settings')}</h4>

              <div className="empdlg-field">
                <span className="empdlg-label">{t('employees.max_shifts')}</span>
                <div className="empdlg-stepper">
                  <button
                    type="button"
                    className="empdlg-step"
                    onClick={() => stepShifts(-1)}
                    disabled={saving || maxShifts.trim() === '0'}
                    aria-label="−"
                  >
                    −
                  </button>
                  <input
                    type="number"
                    min="0"
                    max={MAX_SHIFTS_LIMIT}
                    inputMode="numeric"
                    className="empdlg-input"
                    value={maxShifts}
                    disabled={saving}
                    placeholder="—"
                    onChange={(e) => setMaxShifts(e.target.value)}
                  />
                  <button
                    type="button"
                    className="empdlg-step"
                    onClick={() => stepShifts(1)}
                    disabled={saving}
                    aria-label="+"
                  >
                    +
                  </button>
                  {maxShifts.trim() !== '' && (
                    <button
                      type="button"
                      className="empdlg-clear"
                      onClick={() => setMaxShifts('')}
                      disabled={saving}
                    >
                      {t('employees.no_limit')}
                    </button>
                  )}
                </div>
              </div>

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
            </section>
          )}

          {stats && (
            <>
              <section className="empdlg-section">
                <h4 className="empdlg-section-title">
                  {monthLabel}
                  <span className="empdlg-section-count">
                    {t(`employees.preference_${stats.preference}`)}
                  </span>
                </h4>

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
                        className={`empdlg-day ${d.is_surcharge ? 'is-surcharge' : ''}`}
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
                <h4 className="empdlg-section-title">
                  {t('employees.availability')}
                  <span className="empdlg-section-count">
                    {stats.marked} / {daysInMonth}
                  </span>
                </h4>
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
