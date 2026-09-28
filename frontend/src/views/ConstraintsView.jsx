import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router-dom';
import {
  CONSTRAINT_GROUPS,
  CONSTRAINT_MODE,
  fetchConstraints,
  saveConstraints,
} from '../services/constraintService';
import { useWorkplace, useWorkplaceSwitchGuard } from '../hooks/workplaceContext';
import ConfirmDialog from '../components/ConfirmDialog';
import Toast from '../components/Toast';
import { LockIcon, ResetIcon } from '../components/NavIcons';
import { useToast } from '../hooks/useToast';
import './ConstraintsView.css';

/** The most a weight may be set to; the backend refuses anything above. */
const MAX_WEIGHT = 100000;

/** A weight as the field holds it: text, so a half-typed number survives. */
const weightText = (weight) => (weight == null ? '' : String(weight));

/** The number a weight field stands for, or null while it is not one. */
const parseWeight = (text) => {
  const trimmed = String(text).trim().replace(',', '.');
  if (trimmed === '') return null;
  const number = Number(trimmed);
  return Number.isFinite(number) && number >= 0 && number <= MAX_WEIGHT ? number : null;
};

const draftOf = (entries) =>
  Object.fromEntries(
    entries.map((entry) => [
      entry.code,
      { is_strict: entry.is_strict, weight: weightText(entry.weight) },
    ])
  );

/** Whether a draft row says the same as a setting it is compared with. */
const sameSetting = (row, isStrict, weight) =>
  row.is_strict === isStrict && parseWeight(row.weight) === weight;

/**
 * The scheduling rules of one workplace (scheduler screen).
 *
 * Every rule the generator knows is listed, grouped the way a scheduler
 * thinks about them, and each row carries exactly the controls its kind
 * allows: a fixed rule shows a lock and nothing to change, a switchable one
 * a strict/penalized toggle and a weight, a penalty-only one the weight
 * alone. What the kinds mean and how the weights are weighed against each
 * other is documented in the README, not spelled out here.
 *
 * Edits are a draft until saved, because a weight is typed digit by digit
 * and a half-typed number is not a setting. The draft is guarded against a
 * workplace switch and against leaving the page, like every other editor.
 * "Defaults" only resets the draft; it becomes the workplace's setting when
 * it is saved, the same as any other edit.
 */
const ConstraintsView = () => {
  const { t } = useTranslation();
  const {
    workplaces,
    activeId: selectedId,
    active: selected,
    loading: workplacesLoading,
    error: workplacesError,
    forbidden,
  } = useWorkplace();

  const [entries, setEntries] = useState([]);
  const [draft, setDraft] = useState({});
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState(null);
  const [toast, notify] = useToast();
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    if (selectedId == null) return;
    const seq = ++loadSeq.current;
    setLoading(true);
    setLoadError(false);
    try {
      const data = await fetchConstraints(selectedId);
      if (seq !== loadSeq.current) return;
      setEntries(data.entries);
      setDraft(draftOf(data.entries));
    } catch {
      if (seq !== loadSeq.current) return;
      setEntries([]);
      setDraft({});
      setLoadError(true);
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    load();
  }, [load]);

  /** Rules that can be changed at all; the fixed ones never enter a save. */
  const editable = useMemo(
    () => entries.filter((entry) => entry.mode !== CONSTRAINT_MODE.FIXED),
    [entries]
  );

  const changedCodes = useMemo(
    () =>
      new Set(
        editable
          .filter((entry) => {
            const row = draft[entry.code];
            return row && !sameSetting(row, entry.is_strict, entry.weight);
          })
          .map((entry) => entry.code)
      ),
    [editable, draft]
  );

  const invalidCodes = useMemo(
    () =>
      new Set(
        editable
          .filter((entry) => {
            const row = draft[entry.code];
            // A strict rule keeps its weight for later but does not use it.
            return row && !row.is_strict && parseWeight(row.weight) == null;
          })
          .map((entry) => entry.code)
      ),
    [editable, draft]
  );

  const isDirty = changedCodes.size > 0;

  const draftIsDefault = editable.every((entry) => {
    const row = draft[entry.code];
    return !row || sameSetting(row, entry.default_is_strict, entry.default_weight);
  });

  /* ---------- leave-page guards while there are unsaved changes ---------- */

  useWorkplaceSwitchGuard(isDirty);

  useEffect(() => {
    const handler = (event) => {
      if (!isDirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }) =>
        isDirty && currentLocation.pathname !== nextLocation.pathname,
      [isDirty]
    )
  );

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    setConfirmState({
      onConfirm: () => {
        setConfirmState(null);
        blocker.proceed();
      },
      onCancel: () => {
        setConfirmState(null);
        blocker.reset();
      },
    });
  }, [blocker]);

  /* ---------- draft edits ---------- */

  const updateRow = (code, patch) =>
    setDraft((current) => ({ ...current, [code]: { ...current[code], ...patch } }));

  const resetRow = (entry) =>
    updateRow(entry.code, {
      is_strict: entry.default_is_strict,
      weight: weightText(entry.default_weight),
    });

  const resetAll = () =>
    setDraft((current) => {
      const next = { ...current };
      editable.forEach((entry) => {
        next[entry.code] = {
          is_strict: entry.default_is_strict,
          weight: weightText(entry.default_weight),
        };
      });
      return next;
    });

  const discard = () => setDraft(draftOf(entries));

  const save = async () => {
    if (!isDirty || invalidCodes.size > 0 || selectedId == null) return;
    setSaving(true);
    try {
      const data = await saveConstraints(
        selectedId,
        editable.map((entry) => ({
          code: entry.code,
          is_strict: entry.mode === CONSTRAINT_MODE.SWITCHABLE && draft[entry.code].is_strict,
          weight: parseWeight(draft[entry.code].weight),
        }))
      );
      setEntries(data.entries);
      setDraft(draftOf(data.entries));
      notify(t('constraints.saved'));
    } catch {
      notify(t('constraints.save_error'));
    } finally {
      setSaving(false);
    }
  };

  /* ---------- rendering ---------- */

  if (workplacesLoading) {
    return (
      <div className="page cons">
        <div className="empty-state">
          <span className="spinner" aria-hidden="true" />
          {t('departments.loading')}
        </div>
      </div>
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="page cons">
        <header className="page-header">
          <h1 className="page-title">{t('constraints.title')}</h1>
        </header>
        <div className="alert alert-warning">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const renderMode = (entry, row) => {
    if (entry.mode === CONSTRAINT_MODE.FIXED) {
      return (
        <span className="badge cons-badge is-strict">
          <LockIcon className="icon-sm" />
          {t('constraints.strict')}
        </span>
      );
    }
    if (entry.mode === CONSTRAINT_MODE.PENALTY) {
      return <span className="badge cons-badge">{t('constraints.penalized')}</span>;
    }
    return (
      <div className="segmented cons-toggle" role="group" aria-label={t(`constraints.names.${entry.code}`)}>
        <button
          type="button"
          aria-pressed={row.is_strict}
          onClick={() => updateRow(entry.code, { is_strict: true })}
        >
          {t('constraints.strict')}
        </button>
        <button
          type="button"
          aria-pressed={!row.is_strict}
          onClick={() => updateRow(entry.code, { is_strict: false })}
        >
          {t('constraints.penalized')}
        </button>
      </div>
    );
  };

  const renderRow = (entry) => {
    const row = draft[entry.code] ?? { is_strict: entry.is_strict, weight: weightText(entry.weight) };
    const name = t(`constraints.names.${entry.code}`);
    const isFixed = entry.mode === CONSTRAINT_MODE.FIXED;
    const weightOff = isFixed || row.is_strict;
    const invalid = invalidCodes.has(entry.code) && !weightOff;
    const atDefault = isFixed || sameSetting(row, entry.default_is_strict, entry.default_weight);
    const inputId = `cons-weight-${entry.code}`;

    return (
      <li
        key={entry.code}
        className={[
          'cons-row',
          changedCodes.has(entry.code) ? 'is-changed' : '',
          weightOff ? 'is-strict' : '',
        ]
          .join(' ')
          .trim()}
      >
        <span className="cons-name">{name}</span>
        <span className="cons-mode">{renderMode(entry, row)}</span>
        <span className="cons-weight">
          {!isFixed && (
            <>
              <label className="cons-weight-label" htmlFor={inputId}>
                {t('constraints.weight')}
              </label>
              <input
                id={inputId}
                className="input input-sm cons-weight-input"
                type="number"
                inputMode="decimal"
                min="0"
                max={MAX_WEIGHT}
                step="any"
                value={row.weight}
                disabled={weightOff}
                aria-invalid={invalid || undefined}
                onChange={(event) => updateRow(entry.code, { weight: event.target.value })}
              />
            </>
          )}
        </span>
        <span className="cons-reset">
          {!atDefault && (
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-icon"
              title={t('constraints.reset_one')}
              aria-label={`${t('constraints.reset_one')}: ${name}`}
              onClick={() => resetRow(entry)}
            >
              <ResetIcon className="icon-sm" />
            </button>
          )}
        </span>
      </li>
    );
  };

  return (
    <div className="page cons">
      <header className="page-header">
        <div className="cons-head-name">
          <h1 className="page-title">{t('constraints.title')}</h1>
          {selected?.name && (
            <span className="badge badge-primary cons-workplace">{selected.name}</span>
          )}
        </div>

        <div className="page-actions">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={loading || draftIsDefault}
            onClick={resetAll}
          >
            <ResetIcon />
            {t('constraints.reset_all')}
          </button>
          <button type="button" className="btn" disabled={!isDirty || saving} onClick={discard}>
            {t('constraints.discard')}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!isDirty || invalidCodes.size > 0 || saving}
            onClick={save}
          >
            {saving ? t('constraints.saving') : t('constraints.save')}
          </button>
        </div>
      </header>

      {(workplacesError || loadError) && (
        <div className="alert alert-danger cons-alert" role="alert">
          <span>{t('constraints.load_error')}</span>
          {loadError && (
            <button type="button" className="alert-action" onClick={load}>
              {t('workload.retry')}
            </button>
          )}
        </div>
      )}

      <div className={`cons-groups ${loading ? 'is-loading' : ''}`} aria-busy={loading}>
        {CONSTRAINT_GROUPS.map((group) => {
          const rows = entries.filter((entry) => entry.group === group);
          if (rows.length === 0) return null;
          return (
            <section className="card cons-group" key={group} aria-labelledby={`cons-group-${group}`}>
              <header className="card-header">
                <h2 className="card-title" id={`cons-group-${group}`}>
                  {t(`constraints.groups.${group}`)}
                </h2>
              </header>
              <ul className="cons-list">{rows.map(renderRow)}</ul>
            </section>
          );
        })}
      </div>

      <ConfirmDialog
        open={!!confirmState}
        message={t('constraints.unsaved_warning')}
        confirmLabel={t('departments.leave_anyway')}
        cancelLabel={t('departments.stay')}
        tone="danger"
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />

      <Toast message={toast} />
    </div>
  );
};

export default ConstraintsView;
