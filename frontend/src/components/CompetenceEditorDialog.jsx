import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  DEFAULT_RECOVERY_DAYS,
  ISO_WEEKDAYS,
  clampRecoveryDays,
  normalizeWeekdayRequirements,
  recoveryDaysForTarget,
  recoveryTargetWeekday,
} from '../utils/competenceRequirements';
import './CompetenceEditorDialog.css';

/**
 * Modal editor for one competence inside one scenario.
 *
 * Two of the fields are workplace-wide and two belong to the scenario, and
 * the dialog says so rather than hiding it: renaming a competence renames
 * it everywhere, while the weekly numbers only move this scenario.
 *
 * The recovery section is one row per weekday. Each row is a full Monday-
 * to-Sunday track on which the figure marks the day the duty is worked and
 * the highlighted square marks the next day the same person may work it
 * again; the days in between are the rest. Clicking any square moves that
 * marker, so "how long is the break after a Saturday duty" is answered by
 * pointing at the day it ends. A break can wrap past Sunday, which is why
 * every row also spells the number of days out in words.
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
const emptyDraft = () => ({
  name: '',
  description: '',
  week: ISO_WEEKDAYS.map((weekday) => ({
    weekday,
    required_count: 1,
    recovery_days: DEFAULT_RECOVERY_DAYS,
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

const CompetenceEditorDialog = ({ open, competence, saving, onSave, onCancel }) => {
  const { t } = useTranslation();
  // The parent keys this component by the row being edited, so opening a
  // different competence remounts it and the draft starts from that row.
  const [draft, setDraft] = useState(() => draftFrom(competence));
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

  const setCount = (weekday, value) => {
    const count = Math.max(0, Math.min(1000, Math.round(Number(value) || 0)));
    setDraft((prev) => ({
      ...prev,
      week: prev.week.map((item) =>
        item.weekday === weekday ? { ...item, required_count: count } : item
      ),
    }));
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

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSave) return;
    onSave({
      name: trimmedName,
      description: draft.description.trim() || null,
      weekday_requirements: draft.week.map((item) => ({
        weekday: item.weekday,
        required_count: item.required_count,
        recovery_days: clampRecoveryDays(item.recovery_days),
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
            <h3>{t('scenarios.counts_title')}</h3>
            <p className="ceditor-note">{t('scenarios.counts_hint')}</p>
            <div className="ceditor-counts">
              {draft.week.map((item) => (
                <label
                  key={item.weekday}
                  className={`ceditor-count ${item.weekday >= 5 ? 'is-weekend' : ''}`}
                >
                  <span>{t(`workload.days.${item.weekday}`)}</span>
                  <input
                    type="number"
                    min="0"
                    max="1000"
                    value={item.required_count}
                    onChange={(e) => setCount(item.weekday, e.target.value)}
                  />
                </label>
              ))}
            </div>
          </section>

          <section className="ceditor-section">
            <h3>{t('scenarios.recovery_title')}</h3>
            <p className="ceditor-note">{t('scenarios.recovery_hint')}</p>
            <div className="ceditor-recovery">
              {draft.week.map((item, index) => {
                const target = recoveryTargetWeekday(
                  item.weekday,
                  item.recovery_days
                );
                const rest = new Set(restDays[index]);
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
