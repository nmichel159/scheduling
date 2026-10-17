import { useCallback, useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import PageSkeleton from '../components/Skeleton';
import Toast from '../components/Toast';
import WeekdayPicker from '../components/WeekdayPicker';
import { useToast } from '../hooks/useToast';
import { SHIFT_PREFERENCE } from '../services/employeeService';
import {
  fetchConditions,
  saveConditions,
  WEEKDAY_ANSWER,
  weekdaysOf,
} from '../services/unavailabilityService';
import './ConditionsView.css';

const numberText = (value) => (value == null ? '' : String(value));

/** A whole number 0..31, `null` for an empty field, `undefined` if invalid. */
const parseCount = (text) => {
  const trimmed = text.trim();
  if (trimmed === '') return null;
  const value = Number(trimmed);
  return Number.isInteger(value) && value >= 0 && value <= 31 ? value : undefined;
};

const draftOf = (data) => ({
  max_shifts_per_month: numberText(data.max_shifts_per_month),
  max_surcharge_shifts_per_month: numberText(data.max_surcharge_shifts_per_month),
  shift_preference: data.shift_preference || SHIFT_PREFERENCE.ANY,
  weekday_preferences: weekdaysOf(data.weekday_preferences),
});

/**
 * The employee's standing conditions: what holds for every month unless the
 * restriction calendar says otherwise for one. The scheduler's own answers
 * outrank these and are shown beside them, read-only.
 */
const ConditionsView = () => {
  const { t } = useTranslation();
  const maxId = useId();
  const surchargeId = useId();
  const preferenceId = useId();
  const [saved, setSaved] = useState(null);
  const [draft, setDraft] = useState(null);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, notify] = useToast();

  const load = useCallback(async () => {
    setLoadError(false);
    try {
      const data = await fetchConditions();
      setSaved(data);
      setDraft(draftOf(data));
    } catch {
      setLoadError(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loadError) {
    return (
      <div className="page">
        <div className="alert alert-danger" role="alert">
          <span>{t('conditions.load_error')}</span>
          <button type="button" className="alert-action" onClick={load}>
            {t('workload.retry')}
          </button>
        </div>
      </div>
    );
  }
  if (!draft) return <PageSkeleton />;

  const maxShifts = parseCount(draft.max_shifts_per_month);
  const maxSurcharge = parseCount(draft.max_surcharge_shifts_per_month);
  const invalid = maxShifts === undefined || maxSurcharge === undefined;
  const savedDraft = draftOf(saved);
  const dirty = JSON.stringify(savedDraft) !== JSON.stringify(draft);
  const cap = saved.scheduler_max_shifts_per_month;
  const schedulerDays = weekdaysOf(saved.scheduler_weekday_preferences);
  const schedulerHasDays = schedulerDays.some((answer) => answer !== WEEKDAY_ANSWER.ANY);

  const set = (field, value) => setDraft((previous) => ({ ...previous, [field]: value }));

  const save = async () => {
    if (invalid) return;
    setSaving(true);
    try {
      const data = await saveConditions({
        max_shifts_per_month: maxShifts,
        max_surcharge_shifts_per_month: maxSurcharge,
        shift_preference: draft.shift_preference,
        weekday_preferences: draft.weekday_preferences,
      });
      setSaved(data);
      setDraft(draftOf(data));
      notify(t('conditions.saved'));
    } catch {
      notify(t('workload.save_error'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page conditions">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('conditions.title')}</h1>
        </div>
        <div className="page-actions">
          <button
            type="button"
            className="btn btn-secondary"
            disabled={!dirty || saving}
            onClick={() => setDraft(savedDraft)}
          >
            {t('conditions.discard')}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!dirty || invalid || saving}
            onClick={save}
          >
            {t('conditions.save')}
          </button>
        </div>
      </header>

      <section className="card card-pad conditions-card">
        <h2 className="card-title">{t('conditions.duties')}</h2>
        <div className="conditions-grid">
          <div className="field">
            <label className="field-label" htmlFor={maxId}>
              {t('workload.wish_label')}
            </label>
            <input
              id={maxId}
              className="input"
              type="number"
              min="0"
              max="31"
              inputMode="numeric"
              placeholder={t('workload.wish_placeholder')}
              aria-invalid={maxShifts === undefined || undefined}
              value={draft.max_shifts_per_month}
              onChange={(event) => set('max_shifts_per_month', event.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={surchargeId}>
              {t('workload.surcharge_wish_label')}
            </label>
            <input
              id={surchargeId}
              className="input"
              type="number"
              min="0"
              max="31"
              inputMode="numeric"
              placeholder={t('workload.wish_placeholder')}
              aria-invalid={maxSurcharge === undefined || undefined}
              value={draft.max_surcharge_shifts_per_month}
              onChange={(event) => set('max_surcharge_shifts_per_month', event.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor={preferenceId}>
              {t('conditions.shift_preference')}
            </label>
            <select
              id={preferenceId}
              className="select"
              value={draft.shift_preference}
              onChange={(event) => set('shift_preference', event.target.value)}
            >
              {Object.values(SHIFT_PREFERENCE).map((value) => (
                <option key={value} value={value}>
                  {t(`conditions.preference.${value}`)}
                </option>
              ))}
            </select>
          </div>
          {cap != null && (
            <div className="field">
              <span className="field-label">{t('workload.scheduler_cap')}</span>
              <span className="conditions-value">{cap}</span>
            </div>
          )}
        </div>
      </section>

      <section className="card card-pad conditions-card">
        <h2 className="card-title">{t('conditions.weekdays')}</h2>
        <div className="conditions-weekdays">
          <span className="field-label">{t('conditions.mine')}</span>
          <WeekdayPicker
            label={t('conditions.mine')}
            value={draft.weekday_preferences}
            onChange={(value) => set('weekday_preferences', value)}
          />
          {schedulerHasDays && (
            <>
              <span className="field-label">{t('conditions.scheduler')}</span>
              <WeekdayPicker label={t('conditions.scheduler')} value={schedulerDays} />
            </>
          )}
        </div>
        <div className="conditions-legend">
          {[WEEKDAY_ANSWER.WANT, WEEKDAY_ANSWER.AVOID, WEEKDAY_ANSWER.ANY].map((answer) => (
            <span key={answer} className={`weekday-chip is-${answer} conditions-legend-chip`}>
              {t(`conditions.answer.${answer}`)}
            </span>
          ))}
        </div>
      </section>

      <Toast message={toast} />
    </div>
  );
};

export default ConditionsView;
