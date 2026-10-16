import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router-dom';
import {
  fetchEmployeeCompetenceTable,
  saveEmployeeCompetenceTable,
  fetchCompetences,
  updateCompetence,
  addEmployeeToAmbulance,
  removeEmployeeFromAmbulance,
  fetchAllUsers,
} from '../services/competenceService';
import {
  SHIFT_PREFERENCE,
  fetchEmployeeLoad,
  saveEmployeeSettings,
} from '../services/employeeService';
import { useWorkplace, useWorkplaceSwitchGuard } from '../hooks/workplaceContext';
import CompetenceMatrix from '../components/CompetenceMatrix';
import ConfirmDialog from '../components/ConfirmDialog';
import EmployeeDetailDialog from '../components/EmployeeDetailDialog';
import Toast from '../components/Toast';
import { useToast } from '../hooks/useToast';
import {
  ISO_WEEKDAYS,
  fingerprintCompetenceRequirements,
  groupWeekdaysByRequirements,
  normalizeCompetenceRequirements,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import PageSkeleton from '../components/Skeleton';
import './DepartmentsView.css';

/** The scheduling record of somebody nothing is stored for yet. */
const DEFAULT_SETTINGS = {
  scheduling_active: true,
  max_shifts_per_month: null,
  max_surcharge_shifts_per_month: null,
  shift_preference: SHIFT_PREFERENCE.ANY,
};

/** One person's scheduling record, read off a load row. */
const settingsOf = (row) => ({
  scheduling_active: !row || row.scheduling_active !== false,
  max_shifts_per_month: row?.max_shifts_per_month ?? null,
  max_surcharge_shifts_per_month: row?.max_surcharge_shifts_per_month ?? null,
  shift_preference: row?.shift_preference || SHIFT_PREFERENCE.ANY,
});

const fingerprintSettings = (settings) =>
  JSON.stringify([
    settings.scheduling_active,
    settings.max_shifts_per_month,
    settings.max_surcharge_shifts_per_month,
    settings.shift_preference,
  ]);

/** Deep-copies rows so edits to the draft never mutate the loaded snapshot.
 *  competenceDays maps competenceId -> sorted array of active ISO weekdays
 *  (0=Po..6=Ne); a missing or empty entry means the competence isn't held. */
const cloneRows = (list) =>
  list.map((r) => ({
    ...r,
    settings: { ...r.settings },
    competenceDays: Object.fromEntries(
      Object.entries(r.competenceDays).map(([id, days]) => [id, [...days]])
    ),
  }));

/** Deep-copies columns and their Monday-to-Sunday staffing definitions. */
const cloneColumns = (list) =>
  list.map((column) => ({
    ...column,
    weekday_requirements: normalizeWeekdayRequirements(column).map((item) => ({ ...item })),
  }));

/** Fingerprint of rows — detects employee / competence-assignment changes,
 *  including which weekdays each competence is held on. */
const fingerprintRows = (list) =>
  JSON.stringify(
    [...list]
      .map((r) => ({
        user_id: r.user_id,
        settings: fingerprintSettings(r.settings),
        competence_days: Object.entries(r.competenceDays)
          .filter(([, days]) => days.length > 0)
          .map(([id, days]) => [Number(id), [...days].sort((a, b) => a - b)])
          .sort((a, b) => a[0] - b[0]),
      }))
      .sort((a, b) => a.user_id - b.user_id)
  );

/**
 * Department (ambulance) management view for managers.
 *
 * Works on the ambulance the header switcher points at; each one loads the
 * whole employee x competence table ONCE (bulk GET). Every edit — adding
 * or removing an employee, toggling a competence cell, changing a required
 * count — only touches local state. Nothing reaches the backend until
 * "Save": added/removed employees are synced first (membership calls),
 * then the whole competence table is written in a single bulk PUT, and
 * any changed required_counts are patched per-competence.
 *
 * Beside the competences every row carries the person's own scheduling
 * record — active or not, the two monthly limits and which duties they
 * prefer — so a whole workplace is filled in from this one table. The
 * record is read in bulk with the month's load and only the rows whose
 * record changed are written, one call each, in the same Save.
 *
 * A name in the table opens that person's profile — the same editable
 * dialog the employees screen opens, so the competences of one person can
 * be set by reading their card rather than by finding their row in a wide
 * grid. It is not a second way to write: its picks are folded into the
 * same draft and go out through the same `persist`, which is what keeps it
 * from overwriting an edit made in the matrix behind it.
 */
const DepartmentsView = () => {
  const { t } = useTranslation();

  // Which workplace is being managed comes from the header switcher.
  const {
    workplaces: ambulances,
    activeId: selectedId,
    active: selected,
    loading,
    error: workplacesError,
    forbidden,
  } = useWorkplace();
  const [toast, notify] = useToast();

  const [rows, setRows] = useState([]);
  const [originalRows, setOriginalRows] = useState([]);
  const [columns, setColumns] = useState([]);
  const [originalColumns, setOriginalColumns] = useState([]);
  const [dayGroups, setDayGroups] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState(null);
  const [profileId, setProfileId] = useState(null); // user id

  // Only the newest table request may write state: switching workplaces
  // quickly must not let a slower, older answer land on the new one.
  const loadSeq = useRef(0);

  const isDirty = useMemo(
    () =>
      fingerprintRows(rows) !== fingerprintRows(originalRows) ||
      fingerprintCompetenceRequirements(columns) !==
        fingerprintCompetenceRequirements(originalColumns),
    [rows, originalRows, columns, originalColumns]
  );

  // Let the switcher warn before it pulls another workplace under the table.
  useWorkplaceSwitchGuard(isDirty);

  /* ---------- table for the selected ambulance (bulk load, once) ---------- */

  const loadTable = useCallback(async () => {
    if (selectedId == null) return;
    const seq = ++loadSeq.current;
    setTableLoading(true);
    try {
      const [tableResult, compsResult, usersResult, loadResult] = await Promise.allSettled([
        fetchEmployeeCompetenceTable(selectedId),
        fetchCompetences(selectedId),
        fetchAllUsers(),
        // Any month will do: only the stored preferences are read from it.
        fetchEmployeeLoad(selectedId),
      ]);
      if (seq !== loadSeq.current) return;
      if (tableResult.status === 'rejected') throw tableResult.reason;
      if (compsResult.status === 'rejected') throw compsResult.reason;
      /* Without the stored records the table would show defaults, and a
       * save would write them over what is really there. */
      if (loadResult.status === 'rejected') throw loadResult.reason;

      const loadById = new Map(
        (loadResult.value.employees || []).map((row) => [row.user_id, row])
      );

      const table = tableResult.value;
      const comps = compsResult.value.map(normalizeCompetenceRequirements);
      const nextRows = table.map((row) => ({
        user_id: row.user_id,
        email: row.email,
        full_name: row.full_name,
        settings: settingsOf(loadById.get(row.user_id)),
        // The backend only knows "has this competence" today, not on which
        // days — so a loaded assignment starts out as the whole week. Once
        // the API returns per-weekday data this can read it directly instead.
        competenceDays: Object.fromEntries(
          row.competences.map((c) => [c.id, [...ISO_WEEKDAYS]])
        ),
      }));
      setRows(nextRows);
      setOriginalRows(cloneRows(nextRows));
      setColumns(comps);
      setOriginalColumns(cloneColumns(comps));
      setDayGroups(groupWeekdaysByRequirements(comps));
      if (usersResult.status === 'fulfilled') {
        setAllUsers(usersResult.value);
      } else {
        setAllUsers([]);
        notify(t('departments.load_error'));
      }
    } catch {
      if (seq !== loadSeq.current) return;
      setRows([]);
      setOriginalRows([]);
      setColumns([]);
      setOriginalColumns([]);
      setDayGroups([]);
      notify(t('departments.load_error'));
    } finally {
      if (seq === loadSeq.current) setTableLoading(false);
    }
  }, [selectedId, t, notify]);

  useEffect(() => {
    loadTable();
  }, [loadTable]);

  /* ---------- leave-page guards while there are unsaved changes ---------- */

  useEffect(() => {
    const handler = (e) => {
      if (!isDirty) return;
      e.preventDefault();
      e.returnValue = '';
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
      message: t('departments.unsaved_warning'),
      onConfirm: () => {
        setConfirmState(null);
        blocker.proceed();
      },
      onCancel: () => {
        setConfirmState(null);
        blocker.reset();
      },
    });
  }, [blocker, t]);

  /* ---------- draft edits (local only) ---------- */

  /** Toggle a single weekday of one competence for one employee. */
  const toggleDay = (userId, competenceId, weekday) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.user_id !== userId) return r;
        const current = r.competenceDays[competenceId] || [];
        const has = current.includes(weekday);
        const nextDays = has
          ? current.filter((d) => d !== weekday)
          : [...current, weekday].sort((a, b) => a - b);
        const nextCompetenceDays = { ...r.competenceDays };
        if (nextDays.length > 0) nextCompetenceDays[competenceId] = nextDays;
        else delete nextCompetenceDays[competenceId];
        return { ...r, competenceDays: nextCompetenceDays };
      })
    );
  };

  /** Shortcut: assign every weekday at once, or clear all of them. */
  const toggleWeek = (userId, competenceId) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.user_id !== userId) return r;
        const current = r.competenceDays[competenceId] || [];
        const allOn = current.length === ISO_WEEKDAYS.length;
        const nextCompetenceDays = { ...r.competenceDays };
        if (allOn) delete nextCompetenceDays[competenceId];
        else nextCompetenceDays[competenceId] = [...ISO_WEEKDAYS];
        return { ...r, competenceDays: nextCompetenceDays };
      })
    );
  };

  /** Merge a change into one person's scheduling record. */
  const changeSettings = (userId, patch) => {
    setRows((prev) =>
      prev.map((r) =>
        r.user_id === userId ? { ...r, settings: { ...r.settings, ...patch } } : r
      )
    );
  };

  const addRow = (user) => {
    setRows((prev) => [
      ...prev,
      {
        user_id: user.id,
        email: user.email,
        full_name: user.full_name,
        settings: { ...DEFAULT_SETTINGS },
        competenceDays: {},
      },
    ]);
  };

  const removeRow = (userId) => {
    setRows((prev) => prev.filter((r) => r.user_id !== userId));
  };

  /* ---------- save: membership diff + bulk competence PUT + required_count patches ---------- */

  /**
   * Write one draft of the table.
   *
   * It takes the rows to write instead of reading them off state: the
   * profile dialog folds its own picks in and saves in the same tick, and
   * state set a moment earlier is not visible here yet.
   *
   * The scheduling records go last on purpose: somebody added to the
   * draft a moment ago only becomes an employee of this workplace in the
   * membership step above.
   */
  const persist = async (draftRows) => {
    if (selectedId == null || saving) return;
    setSaving(true);
    // A step that fails does not stop the rest, but it must not end in
    // "Saved" either -- that toast would replace the error a moment later.
    let failed = false;
    try {
      const originalIds = new Set(originalRows.map((r) => r.user_id));
      const currentIds = new Set(draftRows.map((r) => r.user_id));
      const added = draftRows.filter((r) => !originalIds.has(r.user_id));
      const removed = originalRows.filter((r) => !currentIds.has(r.user_id));

      const failedAdds = new Set();
      for (const row of added) {
        try {
          await addEmployeeToAmbulance(selectedId, row.user_id);
        } catch {
          failedAdds.add(row.user_id);
          failed = true;
        }
      }

      for (const row of removed) {
        try {
          await removeEmployeeFromAmbulance(selectedId, row.user_id);
        } catch {
          failed = true;
        }
      }

      // NOTE: the backend today only stores "has this competence" for the
      // whole week (see AmbulanceEmployeeCompetenceUpdate.competence_ids).
      // competence_ids below keeps that working exactly as before (any
      // competence with at least one active day counts as assigned).
      // `competences` carries the actual per-weekday breakdown so nothing
      // is lost from the UI's perspective; the current API ignores unknown
      // fields, so this is safe to send today and just needs šéf to add
      // real per-weekday persistence on the backend (see Slack) before it
      // actually takes effect.
      const payload = draftRows
        .filter((r) => !failedAdds.has(r.user_id))
        .map((r) => {
          const entries = Object.entries(r.competenceDays).filter(([, days]) => days.length > 0);
          return {
            user_id: r.user_id,
            competence_ids: entries.map(([id]) => Number(id)),
            competences: entries.map(([id, days]) => ({
              competence_id: Number(id),
              weekdays: [...days].sort((a, b) => a - b),
            })),
          };
        });

      await saveEmployeeCompetenceTable(selectedId, payload);

      // Patch complete weekday requirements for changed competence columns.
      const origMap = new Map(
        originalColumns.map((column) => [
          column.id,
          JSON.stringify(normalizeWeekdayRequirements(column)),
        ])
      );
      for (const col of columns) {
        const weekdayRequirements = normalizeWeekdayRequirements(col);
        if (origMap.get(col.id) !== JSON.stringify(weekdayRequirements)) {
          try {
            await updateCompetence(selectedId, col.id, {
              weekday_requirements: weekdayRequirements,
            });
          } catch {
            failed = true;
          }
        }
      }

      const originalSettings = new Map(
        originalRows.map((r) => [r.user_id, fingerprintSettings(r.settings)])
      );
      for (const row of draftRows) {
        if (failedAdds.has(row.user_id)) continue;
        const before =
          originalSettings.get(row.user_id) ?? fingerprintSettings(DEFAULT_SETTINGS);
        if (before === fingerprintSettings(row.settings)) continue;
        try {
          await saveEmployeeSettings(selectedId, row.user_id, row.settings);
        } catch {
          failed = true;
        }
      }

      await loadTable();
      setProfileId(null);
      notify(failed ? t('departments.action_error') : t('departments.saved'));
    } catch {
      notify(t('departments.save_error'));
    } finally {
      setSaving(false);
    }
  };

  const handleSave = () => persist(rows);

  /* ---------- one person's profile ----------
   *
   * The same dialog the employees screen opens, and editable here too:
   * it shows the row's draft — competences and scheduling record alike —
   * so the dialog and the table never disagree about one person.
   *
   * Without the month panels the employees screen shows, though. This
   * screen has no month and no way to leave one, so a column of September
   * numbers would be a worse answer than none — the employees screen is
   * where a month is a question that can be asked.
   */

  const openProfile = (userId) => setProfileId(userId);

  /** Fold the dialog's picks into the draft, then let `persist` write it.
   *  The dialog never writes on its own, so it cannot undo an edit made in
   *  the table behind it. */
  const handleProfileSave = ({
    competence_ids: competenceIds,
    scheduling_active: schedulingActive,
    max_shifts_per_month: maxShifts,
    max_surcharge_shifts_per_month: maxSurcharge,
    shift_preference: shiftPreference,
  }) => {
    if (profileId == null) return undefined;
    const nextRows = rows.map((row) =>
      row.user_id === profileId
        ? {
            ...row,
            settings: {
              scheduling_active: schedulingActive,
              max_shifts_per_month: maxShifts,
              max_surcharge_shifts_per_month: maxSurcharge,
              shift_preference: shiftPreference,
            },
            competenceDays: Object.fromEntries(
              competenceIds.map((id) => [id, [...ISO_WEEKDAYS]])
            ),
          }
        : row
    );
    setRows(nextRows);
    return persist(nextRows);
  };

  /* ---------- render ---------- */

  if (loading) {
    return (
      <PageSkeleton
        className="page departments"
        title={t('departments.title')}
        label={t('departments.loading')}
      />
    );
  }

  if (forbidden || (!loading && ambulances.length === 0)) {
    return (
      <div className="page departments">
        <header className="page-header">
          <h1 className="page-title">{t('departments.title')}</h1>
        </header>
        <div className="alert alert-info">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const profileRow =
    (profileId != null && rows.find((r) => r.user_id === profileId)) || null;
  const profileCompetences = profileRow
    ? columns.filter((c) => (profileRow.competenceDays[c.id] || []).length > 0)
    : [];

  return (
    <div className="page departments">
      {/* Pracovisko sa vyberá v bočnej lište, stránka je preto jeden stĺpec:
        * názov, popis pracoviska a Uložiť hore, tabuľka pod tým. */}
      <header className="page-header">
        <div className="departments-heading">
          <h1 className="page-title">{t('departments.title')}</h1>
          {selected && (
            <p className="page-subtitle departments-subtitle">
              <span className="departments-workplace">{selected.name}</span>
              {selected.description && (
                <span className="departments-desc">{selected.description}</span>
              )}
            </p>
          )}
        </div>
        {selected && (
          <div className="page-actions">
            {isDirty && (
              <span className="badge badge-warning badge-dot">
                {t('departments.unsaved')}
              </span>
            )}
            <button
              type="button"
              className="btn btn-primary"
              disabled={!isDirty || saving}
              onClick={handleSave}
            >
              {t('departments.save')}
            </button>
          </div>
        )}
      </header>

      {workplacesError && (
        <div className="alert alert-danger departments-alert" role="alert">
          {t('departments.load_error')}
        </div>
      )}

      {selected && (
        <CompetenceMatrix
          columns={columns}
          dayGroups={dayGroups}
          rows={rows}
          allUsers={allUsers}
          loading={tableLoading}
          onToggleDay={toggleDay}
          onToggleWeek={toggleWeek}
          onChangeSettings={changeSettings}
          onAddRow={addRow}
          onRemoveRow={removeRow}
          onOpenProfile={openProfile}
        />
      )}

      <Toast message={toast} />

      <EmployeeDetailDialog
        key={profileId ?? 'none'}
        employee={profileRow}
        competences={profileCompetences}
        allCompetences={columns}
        settings={profileRow ? profileRow.settings : null}
        saving={saving}
        onSave={handleProfileSave}
        onClose={() => setProfileId(null)}
      />

      <ConfirmDialog
        open={!!confirmState}
        message={confirmState?.message}
        confirmLabel={t('departments.leave_anyway')}
        cancelLabel={t('departments.stay')}
        tone="danger"
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />
    </div>
  );
};

export default DepartmentsView;