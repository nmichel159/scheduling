import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  fetchCompetences,
  createCompetence,
  updateCompetence,
  deleteCompetence,
} from '../services/competenceService';
import { useWorkplace } from '../hooks/workplaceContext';
import ConfirmDialog from '../components/ConfirmDialog';
import {
  ISO_WEEKDAYS,
  normalizeCompetenceRequirements,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import './CompetenceManagerView.css';

/**
 * Competence codebook of one workplace (scheduler screen).
 *
 * This is the registry side of competences: what the workplace defines
 * and what each one means. Who holds which competence is edited in the
 * matrix on "Pracoviská"; the per-day required counts are shown here
 * read-only for the same reason, so the two screens keep one owner each
 * and there is no second draft to save.
 *
 * Unlike the matrix, every action here hits the backend right away
 * (creating, renaming and deleting a competence are registry writes), so
 * the screen has no dirty state and no save button.
 */
const CompetenceManagerView = () => {
  const { t } = useTranslation();
  const {
    workplaces,
    activeId: selectedId,
    active: selected,
    loading,
    error: workplacesError,
    forbidden,
  } = useWorkplace();

  const [competences, setCompetences] = useState([]);
  const [listLoading, setListLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(null); // { id, name, description }
  const [deleteTarget, setDeleteTarget] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

  const load = useCallback(async () => {
    if (selectedId == null) return;
    setListLoading(true);
    try {
      const comps = await fetchCompetences(selectedId);
      setCompetences(comps.map(normalizeCompetenceRequirements));
    } catch {
      setCompetences([]);
      notify(t('competences.load_error'));
    } finally {
      setListLoading(false);
    }
  }, [selectedId, t]);

  useEffect(() => {
    load();
  }, [load]);

  // Switching workplace mid-edit would apply the rename to the wrong row.
  useEffect(() => {
    setEditing(null);
    setDeleteTarget(null);
    setNewName('');
    setNewDescription('');
  }, [selectedId]);

  const rows = useMemo(
    () =>
      competences.map((competence) => ({
        ...competence,
        counts: normalizeWeekdayRequirements(competence).map((item) => item.required_count),
      })),
    [competences]
  );

  const handleCreate = async (e) => {
    e.preventDefault();
    const name = newName.trim();
    if (!name || creating || selectedId == null) return;
    setCreating(true);
    try {
      const created = normalizeCompetenceRequirements(
        await createCompetence(selectedId, name, newDescription.trim() || null)
      );
      setCompetences((prev) => [...prev, created]);
      setNewName('');
      setNewDescription('');
      notify(t('competences.added'));
    } catch {
      notify(t('competences.action_error'));
    } finally {
      setCreating(false);
    }
  };

  const handleSaveEdit = async () => {
    const name = editing.name.trim();
    if (!name) return;
    const description = editing.description.trim();
    try {
      const updated = normalizeCompetenceRequirements(
        await updateCompetence(selectedId, editing.id, {
          name,
          description: description || null,
        })
      );
      setCompetences((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      setEditing(null);
      notify(t('competence_manager.renamed'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const handleDelete = async () => {
    const target = deleteTarget;
    setDeleteTarget(null);
    try {
      await deleteCompetence(selectedId, target.id);
      setCompetences((prev) => prev.filter((c) => c.id !== target.id));
      notify(t('competences.deleted'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  if (loading) {
    return <div className="cmanager"><p>{t('departments.loading')}</p></div>;
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="cmanager">
        <h1 className="cmanager-title">{t('competence_manager.title')}</h1>
        <div className="cmanager-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  return (
    <div className="cmanager">
      <h1 className="cmanager-title">{t('competence_manager.title')}</h1>
      <p className="cmanager-subtitle">{t('competence_manager.subtitle')}</p>

      {workplacesError && <div className="cmanager-banner">{t('competences.load_error')}</div>}

      <section className="cmanager-panel">
        <header className="cmanager-panel-head">
          <h2>{selected?.name}</h2>
        </header>

        <form className="cmanager-new" onSubmit={handleCreate}>
          <input
            className="cmanager-input"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t('competences.new_placeholder')}
            aria-label={t('competence_manager.name')}
          />
          <input
            className="cmanager-input cmanager-input-desc"
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
            placeholder={t('competence_manager.description_placeholder')}
            aria-label={t('competence_manager.description')}
          />
          <button
            type="submit"
            className="cmanager-btn cmanager-btn-primary"
            disabled={!newName.trim() || creating}
          >
            {t('competences.add_competence')}
          </button>
        </form>

        {listLoading && <p className="cmanager-note">{t('departments.loading')}</p>}

        {!listLoading && rows.length === 0 && (
          <p className="cmanager-note">{t('competences.empty')}</p>
        )}

        {rows.length > 0 && (
          <table className="cmanager-table">
            <thead>
              <tr>
                <th className="cmanager-col-name">{t('competence_manager.name')}</th>
                <th>{t('competences.required_count')}</th>
                <th className="cmanager-col-actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isEditing = editing?.id === row.id;
                return (
                  <tr key={row.id}>
                    <td className="cmanager-col-name">
                      {isEditing ? (
                        <div className="cmanager-edit">
                          <input
                            className="cmanager-input"
                            value={editing.name}
                            autoFocus
                            onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                            aria-label={t('competence_manager.name')}
                          />
                          <input
                            className="cmanager-input"
                            value={editing.description}
                            onChange={(e) =>
                              setEditing({ ...editing, description: e.target.value })
                            }
                            placeholder={t('competence_manager.description_placeholder')}
                            aria-label={t('competence_manager.description')}
                          />
                        </div>
                      ) : (
                        <>
                          <b>{row.name}</b>
                          {row.description && (
                            <span className="cmanager-desc">{row.description}</span>
                          )}
                        </>
                      )}
                    </td>

                    <td>
                      <div className="cmanager-week" aria-label={t('competences.required_count')}>
                        {ISO_WEEKDAYS.map((weekday) => (
                          <span
                            key={weekday}
                            className={`cmanager-day ${weekday >= 5 ? 'is-weekend' : ''}`}
                          >
                            <em>{t(`workload.days.${weekday}`)}</em>
                            <b>{row.counts[weekday]}</b>
                          </span>
                        ))}
                      </div>
                    </td>

                    <td className="cmanager-col-actions">
                      {isEditing ? (
                        <>
                          <button
                            type="button"
                            className="cmanager-btn cmanager-btn-primary"
                            disabled={!editing.name.trim()}
                            onClick={handleSaveEdit}
                          >
                            {t('departments.save')}
                          </button>
                          <button
                            type="button"
                            className="cmanager-btn"
                            onClick={() => setEditing(null)}
                          >
                            {t('departments.cancel')}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="cmanager-btn"
                            onClick={() =>
                              setEditing({
                                id: row.id,
                                name: row.name,
                                description: row.description || '',
                              })
                            }
                          >
                            {t('competence_manager.edit')}
                          </button>
                          <button
                            type="button"
                            className="cmanager-btn cmanager-btn-danger"
                            title={t('competences.delete_hint')}
                            onClick={() => setDeleteTarget(row)}
                          >
                            {t('competences.delete')}
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        <p className="cmanager-hint">{t('competence_manager.assignment_hint')}</p>
      </section>

      {toast && (
        <div className="cmanager-toast" role="status">
          {toast}
        </div>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        message={t('competences.confirm_delete_named', { name: deleteTarget?.name })}
        confirmLabel={t('competences.delete')}
        cancelLabel={t('departments.cancel')}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
};

export default CompetenceManagerView;
