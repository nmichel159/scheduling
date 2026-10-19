import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CloseIcon } from './NavIcons';
import {
  DEFAULT_RECOVERY_DAYS,
  DEFAULT_SHIFT_HOURS,
  clampRecoveryDays,
  clampShiftHours,
} from '../utils/competenceRequirements';

/** A whole non-negative count, whatever was typed. */
const clampCount = (value) => {
  const number = Math.floor(Number(value));
  return Number.isFinite(number) && number > 0 ? Math.min(number, 1000) : 0;
};

/** One editable row per competence, in the order the competences are listed. */
const draftRows = (competences, requirements) => {
  const byId = new Map((requirements || []).map((row) => [row.competence_id, row]));
  return competences.map((competence) => {
    const row = byId.get(competence.id);
    return {
      competence_id: competence.id,
      name: competence.name,
      required_count: row?.required_count ?? 0,
      shift_hours: row?.shift_hours ?? DEFAULT_SHIFT_HOURS,
      recovery_days: row?.recovery_days ?? DEFAULT_RECOVERY_DAYS,
      is_surcharge: row?.is_surcharge ?? false,
    };
  });
};

/**
 * Editor of one custom day: its name and, for every competence, how many
 * people it needs, how long the duty is, the rest it earns and whether it
 * is surcharged.
 *
 * Props:
 * - open, saving
 * - customDay: the day being edited, or null for a new one
 * - initialRequirements / initialName: what a new day starts from
 * - competences: [{ id, name }]
 * - onSave({ name, requirements }), onDelete(), onCancel()
 */
const CustomDayDialog = ({
  open,
  saving,
  customDay,
  initialRequirements,
  initialName,
  competences,
  onSave,
  onDelete,
  onCancel,
}) => {
  const { t } = useTranslation();
  const titleId = useId();
  const [name, setName] = useState(customDay?.name ?? initialName ?? '');
  const [rows, setRows] = useState(() =>
    draftRows(competences, customDay?.requirements ?? initialRequirements)
  );

  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  const setField = (competenceId, field, value) =>
    setRows((prev) =>
      prev.map((row) => (row.competence_id === competenceId ? { ...row, [field]: value } : row))
    );

  const trimmed = name.trim();
  const canSave = trimmed.length > 0 && !saving;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSave) return;
    onSave({
      name: trimmed,
      requirements: rows.map((row) => ({
        competence_id: row.competence_id,
        required_count: clampCount(row.required_count),
        shift_hours: clampShiftHours(row.shift_hours),
        recovery_days: clampRecoveryDays(row.recovery_days),
        is_surcharge: !!row.is_surcharge,
      })),
    });
  };

  return (
    <div
      className="dialog-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        className="dialog dialog-lg cday-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={handleSubmit}
      >
        <header className="dialog-header">
          <h2 id={titleId} className="dialog-title">
            {customDay ? t('custom_days.edit_title') : t('custom_days.new_title')}
          </h2>
          <button
            type="button"
            className="dialog-close"
            onClick={onCancel}
            aria-label={t('departments.cancel')}
            title={t('departments.cancel')}
          >
            <CloseIcon />
          </button>
        </header>

        <div className="dialog-body">
          <label className="field">
            <span className="field-label">{t('custom_days.name')}</span>
            <input
              className="input"
              value={name}
              autoFocus
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
            />
          </label>

          <table className="data-table cday-table">
            <thead>
              <tr>
                <th>{t('competence_manager.name')}</th>
                <th>{t('custom_days.people')}</th>
                <th>{t('scenarios.hours_column')}</th>
                <th>{t('scenarios.recovery_column')}</th>
                <th>{t('scenarios.surcharge_row')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="cmanager-empty-row">
                    {t('competences.empty')}
                  </td>
                </tr>
              )}
              {rows.map((row) => (
                <tr key={row.competence_id}>
                  <td>{row.name}</td>
                  <td>
                    <input
                      className="input input-sm cday-number"
                      type="number"
                      min={0}
                      max={1000}
                      value={row.required_count}
                      aria-label={`${row.name}: ${t('custom_days.people')}`}
                      onChange={(e) => setField(row.competence_id, 'required_count', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      className="input input-sm cday-number"
                      type="number"
                      min={0}
                      max={24}
                      step={0.5}
                      value={row.shift_hours}
                      aria-label={`${row.name}: ${t('scenarios.hours_column')}`}
                      onChange={(e) => setField(row.competence_id, 'shift_hours', e.target.value)}
                    />
                  </td>
                  <td>
                    <input
                      className="input input-sm cday-number"
                      type="number"
                      min={0}
                      max={6}
                      value={row.recovery_days}
                      aria-label={`${row.name}: ${t('scenarios.recovery_column')}`}
                      onChange={(e) => setField(row.competence_id, 'recovery_days', e.target.value)}
                    />
                  </td>
                  <td className="cday-check">
                    <input
                      type="checkbox"
                      checked={!!row.is_surcharge}
                      aria-label={`${row.name}: ${t('scenarios.surcharge_row')}`}
                      onChange={(e) => setField(row.competence_id, 'is_surcharge', e.target.checked)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <footer className="dialog-footer">
          {customDay && (
            <button
              type="button"
              className="btn btn-danger-outline cday-delete"
              onClick={onDelete}
              disabled={saving}
            >
              {t('competences.delete')}
            </button>
          )}
          <button type="button" className="btn" onClick={onCancel}>
            {t('departments.cancel')}
          </button>
          <button type="submit" className="btn btn-primary" disabled={!canSave}>
            {t('departments.save')}
          </button>
        </footer>
      </form>
    </div>
  );
};

export default CustomDayDialog;
