import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router-dom';
import {
  fetchEmployeeCompetenceTable,
  saveEmployeeCompetenceTable,
  fetchCompetences,
  createCompetence,
  updateCompetence,
  deleteCompetence,
  addEmployeeToAmbulance,
  removeEmployeeFromAmbulance,
  fetchAllUsers,
} from '../services/competenceService';
import { useWorkplace, useWorkplaceSwitchGuard } from '../hooks/workplaceContext';
import CompetenceMatrix from '../components/CompetenceMatrix';
import ConfirmDialog from '../components/ConfirmDialog';
import {
  ISO_WEEKDAYS,
  fingerprintCompetenceRequirements,
  groupWeekdaysByRequirements,
  mergeEquivalentDayGroups,
  normalizeCompetenceRequirements,
  normalizeWeekdayRequirements,
  extractDayGroup,
  updateGroupRequiredCount,
} from '../utils/competenceRequirements';
import './DepartmentsView.css';

/** Deep-copies rows so edits to the draft never mutate the loaded snapshot.
 *  competenceDays maps competenceId -> sorted array of active ISO weekdays
 *  (0=Po..6=Ne); a missing or empty entry means the competence isn't held. */
const cloneRows = (list) =>
  list.map((r) => ({
    ...r,
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
  const [toast, setToast] = useState(null);

  const [rows, setRows] = useState([]);
  const [originalRows, setOriginalRows] = useState([]);
  const [columns, setColumns] = useState([]);
  const [originalColumns, setOriginalColumns] = useState([]);
  const [dayGroups, setDayGroups] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

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
    setTableLoading(true);
    try {
      const [tableResult, compsResult, usersResult] = await Promise.allSettled([
        fetchEmployeeCompetenceTable(selectedId),
        fetchCompetences(selectedId),
        fetchAllUsers(),
      ]);
      if (tableResult.status === 'rejected') throw tableResult.reason;
      if (compsResult.status === 'rejected') throw compsResult.reason;

      const table = tableResult.value;
      const comps = compsResult.value.map(normalizeCompetenceRequirements);
      const nextRows = table.map((row) => ({
        user_id: row.user_id,
        email: row.email,
        full_name: row.full_name,
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
      setRows([]);
      setOriginalRows([]);
      setColumns([]);
      setOriginalColumns([]);
      setDayGroups([]);
      notify(t('departments.load_error'));
    } finally {
      setTableLoading(false);
    }
  }, [selectedId, t]);

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

  const addRow = (user) => {
    setRows((prev) => [
      ...prev,
      { user_id: user.id, email: user.email, full_name: user.full_name, competenceDays: {} },
    ]);
  };

  const removeRow = (userId) => {
    setRows((prev) => prev.filter((r) => r.user_id !== userId));
  };

  /** Draft-only update for one competence across every day in a grouped row.
   *  Deliberately does NOT re-group/merge dayGroups here: two rows that
   *  happen to reach the same numbers mid-edit (e.g. while clicking one
   *  row's count up towards another row's value) must stay separate rows
   *  until the user actually saves — merging them immediately would pull
   *  both rows under one shared count and make it impossible to set them
   *  to different values. The table only re-groups (merging equal rows or
   *  splitting changed ones) when `loadTable()` re-fetches after Save. */
  const updateRequiredCount = (groupId, competenceId, requiredCount) => {
    setColumns((previousColumns) => {
      const group = dayGroups.find((item) => item.id === groupId);
      if (!group) return previousColumns;
      return updateGroupRequiredCount(
        previousColumns,
        competenceId,
        group.weekdays,
        requiredCount
      );
    });
  };

  /** Build a new day-group out of the days the user picked in the matrix.
   *  `sourceWeekday` is the day they clicked first; every day joining the
   *  group takes that day's counts, so days pulled out of different groups
   *  end up agreeing and the new group is one editable row. Draft-only,
   *  like every other edit here — Save persists it, and the reload
   *  afterwards folds the group back into its neighbour if the counts
   *  turned out to match. */
  const createDayGroup = (weekdays, sourceWeekday) => {
    const next = extractDayGroup(dayGroups, columns, weekdays, sourceWeekday);
    setDayGroups(next.groups);
    setColumns(next.columns);
  };

  /* ---------- codebook actions (immediate — registry, not draft) ---------- */

  const handleAddCompetence = async (name) => {
    try {
      const created = normalizeCompetenceRequirements(
        await createCompetence(selectedId, name)
      );
      setColumns((prev) => {
        const next = [...prev, created];
        setDayGroups((groups) =>
          groups.length > 0
            ? mergeEquivalentDayGroups(groups, next)
            : groupWeekdaysByRequirements(next)
        );
        return next;
      });
      setOriginalColumns((prev) => [...prev, cloneColumns([created])[0]]);
      notify(t('competences.added'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const handleDeleteCompetence = async (competenceId) => {
    try {
      await deleteCompetence(selectedId, competenceId);
      setColumns((prev) => {
        const next = prev.filter((c) => c.id !== competenceId);
        setDayGroups((groups) =>
          next.length > 0 ? mergeEquivalentDayGroups(groups, next) : []
        );
        return next;
      });
      setOriginalColumns((prev) => prev.filter((c) => c.id !== competenceId));
      const stripCompetence = (list) =>
        list.map((r) => {
          if (!(competenceId in r.competenceDays)) return r;
          const nextCompetenceDays = { ...r.competenceDays };
          delete nextCompetenceDays[competenceId];
          return { ...r, competenceDays: nextCompetenceDays };
        });
      setRows(stripCompetence);
      setOriginalRows(stripCompetence);
      notify(t('competences.deleted'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  /* ---------- save: membership diff + bulk competence PUT + required_count patches ---------- */

  const handleSave = async () => {
    if (selectedId == null || saving) return;
    setSaving(true);
    try {
      const originalIds = new Set(originalRows.map((r) => r.user_id));
      const currentIds = new Set(rows.map((r) => r.user_id));
      const added = rows.filter((r) => !originalIds.has(r.user_id));
      const removed = originalRows.filter((r) => !currentIds.has(r.user_id));

      const failedAdds = new Set();
      for (const row of added) {
        try {
          await addEmployeeToAmbulance(selectedId, row.user_id);
        } catch {
          failedAdds.add(row.user_id);
          notify(t('departments.action_error'));
        }
      }

      for (const row of removed) {
        try {
          await removeEmployeeFromAmbulance(selectedId, row.user_id);
        } catch {
          notify(t('departments.action_error'));
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
      const payload = rows
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
            notify(t('competences.action_error'));
          }
        }
      }

      await loadTable();
      notify(t('departments.saved'));
    } catch {
      notify(t('departments.save_error'));
    } finally {
      setSaving(false);
    }
  };

  /* ---------- render ---------- */

  if (loading) {
    return <div className="departments"><p>{t('departments.loading')}</p></div>;
  }

  if (forbidden || (!loading && ambulances.length === 0)) {
    return (
      <div className="departments">
        <h1 className="departments-title">{t('departments.title')}</h1>
        <div className="departments-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  return (
    <div className="departments">
      <h1 className="departments-title">{t('departments.title')}</h1>

      {workplacesError && (
        <div className="departments-banner">{t('departments.load_error')}</div>
      )}

      <div className="departments-layout is-single">
        <section className="departments-detail">
          {selected && (
            <>
              <header className="departments-detail-head">
                <h2 className="departments-detail-title">{selected.name}</h2>
                {selected.description && (
                  <p className="departments-detail-desc">{selected.description}</p>
                )}
                <button
                  type="button"
                  className={`departments-btn departments-btn-primary ${isDirty ? 'is-dirty' : ''}`}
                  disabled={!isDirty || saving}
                  onClick={handleSave}
                >
                  {t('departments.save')}
                </button>
              </header>

              <CompetenceMatrix
                columns={columns}
                dayGroups={dayGroups}
                rows={rows}
                allUsers={allUsers}
                loading={tableLoading}
                onToggleDay={toggleDay}
                onToggleWeek={toggleWeek}
                onAddRow={addRow}
                onRemoveRow={removeRow}
                onAddCompetence={handleAddCompetence}
                onUpdateRequiredCount={updateRequiredCount}
                onCreateDayGroup={createDayGroup}
                onDeleteCompetence={handleDeleteCompetence}
              />
            </>
          )}
        </section>
      </div>

      {toast && (
        <div className="departments-toast" role="status">
          {toast}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmState}
        message={confirmState?.message}
        confirmLabel={t('departments.leave_anyway')}
        cancelLabel={t('departments.stay')}
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />
    </div>
  );
};

export default DepartmentsView;