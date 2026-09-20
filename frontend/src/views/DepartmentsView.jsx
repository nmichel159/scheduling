import { useState, useEffect, useMemo, useCallback } from 'react';
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
  fetchEmployeeSettings,
  saveEmployeeSettings,
} from '../services/employeeService';
import { useWorkplace, useWorkplaceSwitchGuard } from '../hooks/workplaceContext';
import CompetenceMatrix from '../components/CompetenceMatrix';
import ConfirmDialog from '../components/ConfirmDialog';
import EmployeeDetailDialog from '../components/EmployeeDetailDialog';
import {
  ISO_WEEKDAYS,
  fingerprintCompetenceRequirements,
  groupWeekdaysByRequirements,
  normalizeCompetenceRequirements,
  normalizeWeekdayRequirements,
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
  const [profile, setProfile] = useState(null); // { userId, settings }
  const [openingProfile, setOpeningProfile] = useState(null); // user id

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

  /* ---------- save: membership diff + bulk competence PUT + required_count patches ---------- */

  /**
   * Write one draft of the table.
   *
   * It takes the rows to write instead of reading them off state: the
   * profile dialog folds its own picks in and saves in the same tick, and
   * state set a moment earlier is not visible here yet.
   *
   * `profileWrite` carries the one person's scheduling preferences the
   * dialog collected. They are not part of the table draft — they are a
   * record of their own — but they go in the same pass, so the dialog's
   * button means one thing and lands either wholly or not at all. It is
   * written last on purpose: somebody added to the draft a moment ago only
   * becomes an employee of this workplace in the membership step above.
   */
  const persist = async (draftRows, profileWrite = null) => {
    if (selectedId == null || saving) return;
    setSaving(true);
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
            notify(t('competences.action_error'));
          }
        }
      }

      if (profileWrite) {
        try {
          await saveEmployeeSettings(
            selectedId,
            profileWrite.userId,
            profileWrite.settings
          );
        } catch {
          notify(t('departments.action_error'));
        }
      }

      await loadTable();
      setProfile(null);
      notify(t('departments.saved'));
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
   * competences are what this screen is about, and the duty wish and
   * duty-kind preference travel with the person rather than with the
   * table, so they are read when the dialog opens.
   *
   * Without the month panels the employees screen shows, though. This
   * screen has no month and no way to leave one, so a column of September
   * numbers would be a worse answer than none — the employees screen is
   * where a month is a question that can be asked.
   */

  const openProfile = async (userId) => {
    if (selectedId == null || openingProfile != null) return;
    /* Somebody added to the draft a moment ago is not an employee of the
     * workplace yet, so there is nothing on the server to read for them. */
    if (!originalRows.some((r) => r.user_id === userId)) {
      setProfile({
        userId,
        settings: {
          max_shifts_per_month: null,
          shift_preference: SHIFT_PREFERENCE.ANY,
        },
      });
      return;
    }
    setOpeningProfile(userId);
    try {
      setProfile({ userId, settings: await fetchEmployeeSettings(selectedId, userId) });
    } catch {
      notify(t('departments.load_error'));
    } finally {
      setOpeningProfile(null);
    }
  };

  /** Fold the dialog's picks into the draft, then let `persist` write it.
   *  The dialog never writes the table on its own, so it cannot undo an
   *  edit made in the matrix behind it. */
  const handleProfileSave = ({ competence_ids: competenceIds, ...settings }) => {
    if (!profile) return undefined;
    const { userId } = profile;
    const nextRows = rows.map((row) =>
      row.user_id === userId
        ? {
            ...row,
            competenceDays: Object.fromEntries(
              competenceIds.map((id) => [id, [...ISO_WEEKDAYS]])
            ),
          }
        : row
    );
    setRows(nextRows);
    return persist(nextRows, { userId, settings });
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

  const profileRow =
    (profile && rows.find((r) => r.user_id === profile.userId)) || null;
  const profileCompetences = profileRow
    ? columns.filter((c) => (profileRow.competenceDays[c.id] || []).length > 0)
    : [];

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
                onOpenProfile={openProfile}
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

      <EmployeeDetailDialog
        key={profile ? profile.userId : 'none'}
        employee={profileRow}
        competences={profileCompetences}
        allCompetences={columns}
        settings={profile ? profile.settings : null}
        saving={saving}
        onSave={handleProfileSave}
        onClose={() => setProfile(null)}
      />

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