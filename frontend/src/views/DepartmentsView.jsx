import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router-dom';
import {
  fetchMyManagedAmbulances,
  fetchEmployeeCompetenceTable,
  saveEmployeeCompetenceTable,
  fetchCompetences,
  createCompetence,
  deleteCompetence,
  addEmployeeToAmbulance,
  removeEmployeeFromAmbulance,
  fetchAllUsers,
} from '../services/competenceService';
import CompetenceMatrix from '../components/CompetenceMatrix';
import ConfirmDialog from '../components/ConfirmDialog';
import './DepartmentsView.css';

/** Deep-copies rows so edits to the draft never mutate the loaded snapshot. */
const cloneRows = (list) => list.map((r) => ({ ...r, competenceIds: [...r.competenceIds] }));

/** Order/format-independent fingerprint of a row set, used to detect unsaved changes. */
const fingerprint = (list) =>
  JSON.stringify(
    [...list]
      .map((r) => ({ user_id: r.user_id, competence_ids: [...r.competenceIds].sort((a, b) => a - b) }))
      .sort((a, b) => a.user_id - b.user_id)
  );

/**
 * Department (ambulance) management view for managers.
 *
 * Shows all ambulances the current user manages; selecting one loads the
 * whole employee x competence table ONCE (bulk GET). Every edit — adding
 * or removing an employee, toggling a competence cell — only touches
 * local state. Nothing reaches the backend until "Save": added/removed
 * employees are synced first (membership calls), then the whole
 * competence table is written in a single bulk PUT.
 */
const DepartmentsView = () => {
  const { t } = useTranslation();

  const currentUser = useMemo(() => {
    try {
      return JSON.parse(localStorage.getItem('user')) || null;
    } catch {
      return null;
    }
  }, []);

  const [ambulances, setAmbulances] = useState([]);
  const [selectedId, setSelectedId] = useState(null);

  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);

  const [rows, setRows] = useState([]);
  const [originalRows, setOriginalRows] = useState([]);
  const [columns, setColumns] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

  const isDirty = useMemo(
    () => fingerprint(rows) !== fingerprint(originalRows),
    [rows, originalRows]
  );

  /* ---------- initial load: ambulances I manage ---------- */

  useEffect(() => {
    if (!currentUser?.id) return;
    let cancelled = false;

    (async () => {
      setLoading(true);
      setError(null);
      try {
        const myAmbulances = await fetchMyManagedAmbulances();
        if (cancelled) return;
        setAmbulances(myAmbulances);
        if (myAmbulances.length > 0) setSelectedId(myAmbulances[0].id);
      } catch (err) {
        if (cancelled) return;
        if (err?.response?.status === 403) setForbidden(true);
        else setError(t('departments.load_error'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [currentUser, t]);

  /* ---------- table for the selected ambulance (bulk load, once) ---------- */

  const loadTable = useCallback(async () => {
    if (selectedId == null) return;
    setTableLoading(true);
    try {
      const [table, comps, users] = await Promise.all([
        fetchEmployeeCompetenceTable(selectedId),
        fetchCompetences(selectedId),
        fetchAllUsers(),
      ]);
      const nextRows = table.map((row) => ({
        user_id: row.user_id,
        email: row.email,
        full_name: row.full_name,
        competenceIds: row.competences.map((c) => c.id),
      }));
      setRows(nextRows);
      setOriginalRows(cloneRows(nextRows));
      setColumns(comps);
      setAllUsers(users);
    } catch {
      setRows([]);
      setOriginalRows([]);
      setColumns([]);
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

  const selectAmbulance = (id) => {
    if (id === selectedId) return;
    if (!isDirty) {
      setSelectedId(id);
      return;
    }
    setConfirmState({
      message: t('departments.unsaved_warning'),
      onConfirm: () => {
        setConfirmState(null);
        setSelectedId(id);
      },
      onCancel: () => setConfirmState(null),
    });
  };

  /* ---------- draft edits (local only) ---------- */

  const toggleCell = (userId, competenceId) => {
    setRows((prev) =>
      prev.map((r) => {
        if (r.user_id !== userId) return r;
        const has = r.competenceIds.includes(competenceId);
        return {
          ...r,
          competenceIds: has
            ? r.competenceIds.filter((id) => id !== competenceId)
            : [...r.competenceIds, competenceId],
        };
      })
    );
  };

  const addRow = (user) => {
    setRows((prev) => [
      ...prev,
      { user_id: user.id, email: user.email, full_name: user.full_name, competenceIds: [] },
    ]);
  };

  const removeRow = (userId) => {
    setRows((prev) => prev.filter((r) => r.user_id !== userId));
  };

  /* ---------- codebook actions (immediate — registry, not draft) ---------- */

  const handleAddCompetence = async (name) => {
    try {
      const created = await createCompetence(selectedId, name);
      setColumns((prev) => [...prev, created]);
      notify(t('competences.added'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const handleDeleteCompetence = async (competenceId) => {
    try {
      await deleteCompetence(selectedId, competenceId);
      setColumns((prev) => prev.filter((c) => c.id !== competenceId));
      const stripCompetence = (list) =>
        list.map((r) => ({
          ...r,
          competenceIds: r.competenceIds.filter((id) => id !== competenceId),
        }));
      setRows(stripCompetence);
      setOriginalRows(stripCompetence);
      notify(t('competences.deleted'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  /* ---------- save: membership diff, then one bulk competence PUT ---------- */

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

      const payload = rows
        .filter((r) => !failedAdds.has(r.user_id))
        .map((r) => ({ user_id: r.user_id, competence_ids: r.competenceIds }));

      await saveEmployeeCompetenceTable(selectedId, payload);

      await loadTable();
      notify(t('departments.saved'));
    } catch {
      notify(t('departments.save_error'));
    } finally {
      setSaving(false);
    }
  };

  /* ---------- render ---------- */

  const selected = ambulances.find((a) => a.id === selectedId) || null;
  const showList = ambulances.length > 1; // 1 klinika = bez bočného zoznamu

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
      <p className="departments-subtitle">{t('departments.subtitle')}</p>

      {error && <div className="departments-banner">{error}</div>}

      <div className={`departments-layout ${showList ? '' : 'is-single'}`}>
        {/* left: my ambulances — zobrazí sa len pri viacerých klinikách */}
        {showList && (
          <nav className="departments-list" aria-label={t('departments.my_ambulances')}>
            {ambulances.map((a) => (
              <button
                type="button"
                key={a.id}
                className={`departments-item ${a.id === selectedId ? 'is-selected' : ''}`}
                onClick={() => selectAmbulance(a.id)}
              >
                <span className="departments-item-name">{a.name}</span>
                {a.description && <span className="departments-item-desc">{a.description}</span>}
              </button>
            ))}
          </nav>
        )}

        {/* right: employee x competence table for the selected ambulance */}
        <section className="departments-detail">
          {selected && (
            <>
              <header className="departments-detail-head">
                <h2 className="departments-detail-title">{selected.name}</h2>
                {!showList && selected.description && (
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
                rows={rows}
                allUsers={allUsers}
                loading={tableLoading}
                onToggleCell={toggleCell}
                onAddRow={addRow}
                onRemoveRow={removeRow}
                onAddCompetence={handleAddCompetence}
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
