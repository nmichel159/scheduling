import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DEFAULT_RECOVERY_DAYS,
  DEFAULT_SHIFT_HOURS,
  ISO_WEEKDAYS,
  MAX_RECOVERY_DAYS,
  REQUIREMENT_SLOTS,
  SPECIAL_DAY_SLOT,
  clampRecoveryDays,
  clampShiftHours,
  defaultIsSurcharge,
  normalizeWeekdayRequirements,
  recoveryDaysForTarget,
  recoveryTargetWeekday,
} from '../utils/competenceRequirements';
import './CompetenceEditorDialog.css';

/**
 * Modal editor for one competence inside one scenario.
 *
 * The name and description are workplace-wide and the weekly numbers
 * belong to the scenario, and the dialog says so rather than hiding it:
 * renaming a competence renames it everywhere, while the counts, hours and
 * recovery only move this scenario.
 *
 * The people needed, the hours worked and whether those hours are paid with
 * a surcharge sit one under the other on the same Monday-to-Sunday grid, so
 * a weekday is one column and reads top to bottom. An eighth column follows
 * the seven: the day of rest, which is what a public holiday is staffed
 * from whatever weekday it falls on. Which dates those are is not decided
 * here -- the holiday library and the Special days screen answer that -- so
 * the column is set apart from the week rather than pretending to be part
 * of it.
 *
 * Surcharge belongs here, beside the hours of the day, because that is what
 * it actually follows: the same competence is ordinary on a Tuesday and
 * surcharged on a Sunday. A new competence starts out surcharged on the
 * weekend and on the day of rest, and nowhere else. Either number row can
 * be tied together with its "same every day" box: the fields stay on screen
 * either way, and typing into any of them writes the whole row.
 *
 * The recovery section is one row per weekday. Each row is a full Monday-
 * to-Sunday track on which the figure marks the day the duty is worked and
 * the highlighted square marks the next day the same person may work it
 * again; the days in between are the rest. Clicking any square moves that
 * marker, so "how long is the break after a Saturday duty" is answered by
 * pointing at the day it ends. A break can wrap past Sunday, which is why
 * every row also spells the number of days out in words.
 *
 * The day of rest gets a plain number instead of a track: it has no fixed
 * weekday, so there is no square on a Monday-to-Sunday strip that could
 * mean "the day this duty's break ends".
 *
 * Enter walks to the next field instead of submitting: the form is a
 * table of numbers to fill in, and losing it to a stray Enter on the
 * second of fifteen fields would be the wrong trade. Saving is the button.
 *
 * The parent must key this component by the row being edited, so that
 * opening another competence starts a fresh draft.
 *
 * Props:
 * - open: whether to render
 * - competence: the record being edited, or null to create a new one
 * - saving: disables the form while the parent persists
 * - onSave({ name, description, weekday_requirements }): Promise
 * - onCancel()
 */
/** Whether a slot is the day of rest rather than one of the seven days. */
const isSpecialDay = (slot) => Number(slot) === SPECIAL_DAY_SLOT;

/** Column heading for one slot: a weekday's short name, or the holiday mark. */
const dayLabel = (t, slot) =>
  isSpecialDay(slot) ? t('special_days.column_short') : t(`workload.days.${slot}`);

/** Shared modifiers of a slot's cell: shaded on the weekend, set apart on
 *  the day of rest. */
const dayClass = (base, slot) =>
  [base, slot >= 5 && slot <= 6 ? 'is-weekend' : '', isSpecialDay(slot) ? 'is-special' : '']
    .join(' ')
    .trim();

const emptyDraft = () => ({
  name: '',
  description: '',
  week: REQUIREMENT_SLOTS.map((weekday) => ({
    weekday,
    required_count: 1,
    recovery_days: DEFAULT_RECOVERY_DAYS,
    shift_hours: DEFAULT_SHIFT_HOURS,
    is_surcharge: defaultIsSurcharge(weekday),
  })),
});

const draftFrom = (competence) =>
  competence
    ? {
        name: competence.name || '',
        description: competence.description || '',
        week: normalizeWeekdayRequirements(competence),
      }
    : emptyDraft();

/** A week that already reads the same everywhere opens tied together. */
const isUniform = (week, field) =>
  week.every((item) => item[field] === week[0][field]);

const clampRequiredCount = (value) =>
  Math.max(0, Math.min(1000, Math.round(Number(value) || 0)));

const CLAMP_BY_FIELD = {
  required_count: clampRequiredCount,
  shift_hours: clampShiftHours,
};

/* A field holds the raw text until it is left, and only then becomes a
   number again. Clamping every keystroke would fight the user: clearing
   the field would put a 0 back, and typing over that 0 would read "05". */

const CompetenceEditorDialog = ({ open, competence, saving, onSave, onCancel }) => {
  const { t } = useTranslation();
  // The parent keys this component by the row being edited, so opening a
  // different competence remounts it and the draft starts from that row.
  const [draft, setDraft] = useState(() => draftFrom(competence));
  const [sameCounts, setSameCounts] = useState(() =>
    isUniform(draftFrom(competence).week, 'required_count')
  );
  const [sameHours, setSameHours] = useState(() =>
    isUniform(draftFrom(competence).week, 'shift_hours')
  );
  const nameRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    nameRef.current?.focus();
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onCancel]);

  const trimmedName = draft.name.trim();
  const canSave = trimmedName.length > 0 && !saving;

  /** Write one field, on one weekday or on all seven when they are tied. */
  const setField = (field, weekday, value, wholeWeek) => {
    setDraft((prev) => ({
      ...prev,
      week: prev.week.map((item) =>
        wholeWeek || item.weekday === weekday ? { ...item, [field]: value } : item
      ),
    }));
  };

  /** Turn what was typed into the number that will be saved. */
  const commitField = (field, weekday, wholeWeek) =>
    setField(field, weekday, CLAMP_BY_FIELD[field](draft.week[weekday][field]), wholeWeek);

  // Tying a row together levels it on Monday rather than on the day the
  // user happens to click next, so the result is visible immediately.
  const tieRow = (field, next) => {
    if (field === 'required_count') setSameCounts(next);
    else setSameHours(next);
    if (next) setField(field, null, CLAMP_BY_FIELD[field](draft.week[0][field]), true);
  };

  const setRecoveryTarget = (weekday, targetWeekday) => {
    setDraft((prev) => ({
      ...prev,
      week: prev.week.map((item) =>
        item.weekday === weekday
          ? {
              ...item,
              recovery_days: recoveryDaysForTarget(weekday, targetWeekday),
            }
          : item
      ),
    }));
  };

  /** Days that are neither the duty nor the return — the break itself. */
  const restDays = useMemo(
    () =>
      draft.week.map((item) =>
        Array.from(
          { length: clampRecoveryDays(item.recovery_days) },
          (_unused, offset) => (item.weekday + offset + 1) % 7
        )
      ),
    [draft.week]
  );

  /** Enter moves on rather than submitting; the last field falls through
   *  to the save button, which is the next thing in the form anyway. */
  const handleFormKeyDown = (e) => {
    if (e.key !== 'Enter' || e.target.tagName === 'TEXTAREA') return;
    if (e.target.tagName === 'BUTTON') return;
    e.preventDefault();
    const fields = [...e.currentTarget.querySelectorAll('input, select, button')].filter(
      (field) => !field.disabled && field.type !== 'hidden'
    );
    const next = fields[fields.indexOf(e.target) + 1];
    next?.focus();
    if (next?.select) next.select();
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSave) return;
    onSave({
      name: trimmedName,
      description: draft.description.trim() || null,
      weekday_requirements: draft.week.map((item) => ({
        weekday: item.weekday,
        required_count: clampRequiredCount(item.required_count),
        recovery_days: clampRecoveryDays(item.recovery_days),
        shift_hours: clampShiftHours(item.shift_hours),
        is_surcharge: !!item.is_surcharge,
      })),
    });
  };

  if (!open) return null;

  return (
    <div
      className="ceditor-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        className="ceditor"
        role="dialog"
        aria-modal="true"
        aria-label={
          competence ? t('scenarios.edit_competence') : t('scenarios.new_competence')
        }
        onSubmit={handleSubmit}
        onKeyDown={handleFormKeyDown}
      >
        <header className="ceditor-head">
          <h2>
            {competence
              ? t('scenarios.edit_competence')
              : t('scenarios.new_competence')}
          </h2>
          <button
            type="button"
            className="ceditor-close"
            onClick={onCancel}
            aria-label={t('departments.cancel')}
          >
            ×
          </button>
        </header>

        <div className="ceditor-body">
          <label className="ceditor-field">
            <span>{t('competence_manager.name')}</span>
            <input
              ref={nameRef}
              className="ceditor-input"
              value={draft.name}
              maxLength={200}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>

          <label className="ceditor-field">
            <span>{t('competence_manager.description')}</span>
            <input
              className="ceditor-input"
              value={draft.description}
              maxLength={2000}
              placeholder={t('competence_manager.description_placeholder')}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </label>

          <section className="ceditor-section">
            <h3>{t('scenarios.week_title')}</h3>
            <div className="ceditor-grid">
              <div className="ceditor-grid-row ceditor-grid-head">
                <span className="ceditor-grid-label" />
                {REQUIREMENT_SLOTS.map((weekday) => (
                  <span
                    key={weekday}
                    className={dayClass('ceditor-grid-day', weekday)}
                    title={isSpecialDay(weekday) ? t('special_days.column_hint') : undefined}
                  >
                    {dayLabel(t, weekday)}
                  </span>
                ))}
                <span className="ceditor-grid-tie" />
              </div>

              {[
                {
                  field: 'required_count',
                  label: t('competences.required_count'),
                  tied: sameCounts,
                  step: '1',
                  max: '1000',
                },
                {
                  field: 'shift_hours',
                  label: t('scenarios.hours_column'),
                  tied: sameHours,
                  step: '0.25',
                  max: '24',
                },
              ].map((row) => (
                <div className="ceditor-grid-row" key={row.field}>
                  <span className="ceditor-grid-label">{row.label}</span>
                  {draft.week.map((item) => (
                    <input
                      key={item.weekday}
                      className={dayClass('ceditor-grid-input', item.weekday)}
                      type="number"
                      min="0"
                      max={row.max}
                      step={row.step}
                      value={item[row.field]}
                      aria-label={`${row.label} — ${dayLabel(t, item.weekday)}`}
                      onChange={(e) =>
                        setField(row.field, item.weekday, e.target.value, row.tied)
                      }
                      onBlur={() =>
                        commitField(row.field, item.weekday, row.tied)
                      }
                    />
                  ))}
                  <label className="ceditor-grid-tie">
                    <input
                      type="checkbox"
                      checked={row.tied}
                      onChange={(e) => tieRow(row.field, e.target.checked)}
                    />
                    <span>{t('scenarios.same_every_day')}</span>
                  </label>
                </div>
              ))}

              <div className="ceditor-grid-row">
                <span className="ceditor-grid-label">
                  {t('scenarios.surcharge_row')}
                </span>
                {draft.week.map((item) => (
                  <label
                    key={item.weekday}
                    className={`${dayClass('ceditor-grid-check', item.weekday)} ${item.is_surcharge ? 'is-surcharge' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={!!item.is_surcharge}
                      aria-label={`${t('scenarios.surcharge_row')} — ${dayLabel(t, item.weekday)}`}
                      onChange={(e) =>
                        setField(
                          'is_surcharge',
                          item.weekday,
                          e.target.checked,
                          false
                        )
                      }
                    />
                  </label>
                ))}
                <span className="ceditor-grid-tie ceditor-grid-hint">
                  {t('scenarios.surcharge_hint')}
                </span>
              </div>
            </div>
          </section>

          <section className="ceditor-section">
            <h3>{t('scenarios.recovery_title')}</h3>
            <div className="ceditor-recovery">
              {draft.week.map((item, index) => {
                const target = recoveryTargetWeekday(
                  item.weekday,
                  item.recovery_days
                );
                const rest = new Set(restDays[index]);

                // A day of rest has no weekday, so no square on the strip
                // could mean the day its break ends. The number itself is
                // the whole answer here.
                if (isSpecialDay(item.weekday)) {
                  return (
                    <div
                      className="ceditor-recovery-row is-special"
                      key={item.weekday}
                    >
                      <span className="ceditor-recovery-label">
                        {t('special_days.column_short')}
                      </span>
                      <div className="ceditor-recovery-plain">
                        <input
                          className="ceditor-grid-input"
                          type="number"
                          min="0"
                          max={MAX_RECOVERY_DAYS}
                          step="1"
                          value={item.recovery_days}
                          aria-label={t('scenarios.recovery_row', {
                            day: t('special_days.column_short'),
                          })}
                          onChange={(e) =>
                            setField(
                              'recovery_days',
                              item.weekday,
                              e.target.value,
                              false
                            )
                          }
                          onBlur={() =>
                            setField(
                              'recovery_days',
                              item.weekday,
                              clampRecoveryDays(item.recovery_days),
                              false
                            )
                          }
                        />
                        <span className="ceditor-grid-hint">
                          {t('special_days.recovery_hint')}
                        </span>
                      </div>
                      <span className="ceditor-recovery-value">
                        {t('scenarios.recovery_days', {
                          count: clampRecoveryDays(item.recovery_days),
                        })}
                      </span>
                    </div>
                  );
                }

                return (
                  <div className="ceditor-recovery-row" key={item.weekday}>
                    <span className="ceditor-recovery-label">
                      {t(`workload.days.${item.weekday}`)}
                    </span>
                    <div
                      className="ceditor-track"
                      role="group"
                      aria-label={t('scenarios.recovery_row', {
                        day: t(`workload.days.${item.weekday}`),
                      })}
                    >
                      {ISO_WEEKDAYS.map((weekday) => {
                        const isSource = weekday === item.weekday;
                        const isTarget = weekday === target;
                        return (
                          <button
                            type="button"
                            key={weekday}
                            className={[
                              'ceditor-slot',
                              isSource ? 'is-source' : '',
                              isTarget ? 'is-target' : '',
                              rest.has(weekday) ? 'is-rest' : '',
                            ]
                              .join(' ')
                              .trim()}
                            aria-pressed={isTarget}
                            title={t('scenarios.recovery_slot', {
                              day: t(`workload.days.${weekday}`),
                            })}
                            onClick={() => setRecoveryTarget(item.weekday, weekday)}
                          >
                            <em>{t(`workload.days.${weekday}`)}</em>
                            <b aria-hidden="true">{isSource ? '🧍' : ''}</b>
                          </button>
                        );
                      })}
                    </div>
                    <span className="ceditor-recovery-value">
                      {t('scenarios.recovery_days', {
                        count: clampRecoveryDays(item.recovery_days),
                      })}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        </div>

        <footer className="ceditor-actions">
          <button type="button" className="cmanager-btn" onClick={onCancel}>
            {t('departments.cancel')}
          </button>
          <button
            type="submit"
            className="cmanager-btn cmanager-btn-primary"
            disabled={!canSave}
          >
            {t('departments.save')}
          </button>
        </footer>
      </form>
    </div>
  );
};

export default CompetenceEditorDialog;
