import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  createScenario,
  createScenarioCompetence,
  deleteScenario,
  deleteScenarioCompetence,
  fetchScenarioCompetences,
  fetchScenarios,
  updateScenario,
  updateScenarioCompetence,
} from '../services/competenceService';
import { useWorkplace } from '../hooks/workplaceContext';
import ConfirmDialog from '../components/ConfirmDialog';
import CompetenceEditorDialog from '../components/CompetenceEditorDialog';
import {
  ISO_WEEKDAYS,
  clampRecoveryDays,
  normalizeCompetenceRequirements,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import './CompetenceManagerView.css';

/**
 * Competence scenarios of one workplace (scheduler screen).
 *
 * The screen has two modes and swaps between them in place, without a
 * route change: a list of the workplace's scenarios, and one scenario
 * opened for editing. Editing a single competence happens in a modal on
 * top of the second mode.
 *
 * The competence list itself is workplace-wide — the same three or four
 * competences exist in every scenario. What a scenario owns is their
 * parameters: how many people each one needs on each weekday, and how much
 * recovery a duty costs. Exactly one scenario is selected, and that is the
 * one the schedule generator and the other screens read; the rest are
 * model cases kept side by side.
 *
 * Every action here hits the backend right away — these are registry
 * writes, not a draft — so the screen has no dirty state and no save
 * button outside the modal.
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

  const [scenarios, setScenarios] = useState([]);
  const [scenariosLoading, setScenariosLoading] = useState(false);
  const [openScenarioId, setOpenScenarioId] = useState(null);
  const [competences, setCompetences] = useState([]);
  const [competencesLoading, setCompetencesLoading] = useState(false);

  const [toast, setToast] = useState(null);
  const [newScenarioName, setNewScenarioName] = useState('');
  const [creatingScenario, setCreatingScenario] = useState(false);
  const [renaming, setRenaming] = useState(null); // { id, name }
  const [editorTarget, setEditorTarget] = useState(null); // competence | 'new'
  const [savingCompetence, setSavingCompetence] = useState(false);
  const [deleteScenarioTarget, setDeleteScenarioTarget] = useState(null);
  const [deleteCompetenceTarget, setDeleteCompetenceTarget] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2400);
  };

  const loadScenarios = useCallback(async () => {
    if (selectedId == null) return;
    setScenariosLoading(true);
    try {
      setScenarios(await fetchScenarios(selectedId));
    } catch {
      setScenarios([]);
      notify(t('scenarios.load_error'));
    } finally {
      setScenariosLoading(false);
    }
  }, [selectedId, t]);

  useEffect(() => {
    loadScenarios();
  }, [loadScenarios]);

  // Switching workplace mid-edit would apply the change to the wrong row.
  useEffect(() => {
    setOpenScenarioId(null);
    setCompetences([]);
    setRenaming(null);
    setEditorTarget(null);
    setDeleteScenarioTarget(null);
    setDeleteCompetenceTarget(null);
    setNewScenarioName('');
  }, [selectedId]);

  const loadCompetences = useCallback(
    async (scenarioId) => {
      if (selectedId == null || scenarioId == null) return;
      setCompetencesLoading(true);
      try {
        const rows = await fetchScenarioCompetences(selectedId, scenarioId);
        setCompetences(rows.map(normalizeCompetenceRequirements));
      } catch {
        setCompetences([]);
        notify(t('competences.load_error'));
      } finally {
        setCompetencesLoading(false);
      }
    },
    [selectedId, t]
  );

  const openScenario = (scenario) => {
    setOpenScenarioId(scenario.id);
    setCompetences([]);
    loadCompetences(scenario.id);
  };

  const closeScenario = () => {
    setOpenScenarioId(null);
    setCompetences([]);
  };

  const openScenarioRecord = useMemo(
    () => scenarios.find((item) => item.id === openScenarioId) || null,
    [scenarios, openScenarioId]
  );

  // A scenario deleted in another tab leaves the detail pointing at
  // nothing; fall back to the list rather than showing an empty shell.
  useEffect(() => {
    if (openScenarioId != null && !scenariosLoading && scenarios.length > 0 && !openScenarioRecord) {
      setOpenScenarioId(null);
      setCompetences([]);
    }
  }, [openScenarioId, openScenarioRecord, scenarios.length, scenariosLoading]);

  const nextScenarioName = () => {
    const used = new Set(scenarios.map((item) => item.name));
    let index = scenarios.length + 1;
    while (used.has(t('scenarios.default_name', { index }))) index += 1;
    return t('scenarios.default_name', { index });
  };

  const handleCreateScenario = async (e) => {
    e.preventDefault();
    if (creatingScenario || selectedId == null) return;
    const name = newScenarioName.trim() || nextScenarioName();
    setCreatingScenario(true);
    try {
      // A new scenario starts from the selected one's numbers: the
      // competences are the same either way, so copying is the difference
      // between tweaking a model case and retyping every day of it.
      const source = scenarios.find((item) => item.is_selected);
      const created = await createScenario(selectedId, name, source?.id ?? null);
      setScenarios((prev) => [...prev, created]);
      setNewScenarioName('');
      notify(t('scenarios.added'));
      openScenario(created);
    } catch {
      notify(t('competences.action_error'));
    } finally {
      setCreatingScenario(false);
    }
  };

  const handleSelectScenario = async (scenario) => {
    if (scenario.is_selected) return;
    try {
      await updateScenario(selectedId, scenario.id, { is_selected: true });
      setScenarios((prev) =>
        prev.map((item) => ({ ...item, is_selected: item.id === scenario.id }))
      );
      notify(t('scenarios.selected_toast', { name: scenario.name }));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const handleSaveRename = async () => {
    const name = renaming.name.trim();
    if (!name) return;
    try {
      const updated = await updateScenario(selectedId, renaming.id, { name });
      setScenarios((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setRenaming(null);
      notify(t('scenarios.renamed'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const handleDeleteScenario = async () => {
    const target = deleteScenarioTarget;
    setDeleteScenarioTarget(null);
    try {
      await deleteScenario(selectedId, target.id);
      if (openScenarioId === target.id) closeScenario();
      notify(t('scenarios.deleted'));
      // The backend may have moved the selection to another scenario, so
      // the whole list is reloaded rather than patched in place.
      await loadScenarios();
    } catch {
      notify(t('scenarios.delete_error'));
    }
  };

  const handleSaveCompetence = async (payload) => {
    if (savingCompetence || openScenarioId == null) return;
    setSavingCompetence(true);
    try {
      if (editorTarget === 'new') {
        const created = normalizeCompetenceRequirements(
          await createScenarioCompetence(selectedId, openScenarioId, payload)
        );
        setCompetences((prev) => [...prev, created]);
        notify(t('competences.added'));
        // A new competence exists in every scenario, so the counts shown
        // on the list mode are stale until they are read back.
        loadScenarios();
      } else {
        const updated = normalizeCompetenceRequirements(
          await updateScenarioCompetence(
            selectedId,
            openScenarioId,
            editorTarget.id,
            payload
          )
        );
        setCompetences((prev) =>
          prev.map((item) => (item.id === updated.id ? updated : item))
        );
        notify(t('scenarios.competence_saved'));
      }
      setEditorTarget(null);
    } catch {
      notify(t('competences.action_error'));
    } finally {
      setSavingCompetence(false);
    }
  };

  const handleDeleteCompetence = async () => {
    const target = deleteCompetenceTarget;
    setDeleteCompetenceTarget(null);
    try {
      await deleteScenarioCompetence(selectedId, openScenarioId, target.id);
      setCompetences((prev) => prev.filter((item) => item.id !== target.id));
      notify(t('competences.deleted'));
      loadScenarios();
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const rows = useMemo(
    () =>
      competences.map((competence) => ({
        ...competence,
        week: normalizeWeekdayRequirements(competence),
      })),
    [competences]
  );

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

  const sortedCompetences = [...rows].sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="cmanager">
      <h1 className="cmanager-title">{t('competence_manager.title')}</h1>
      <p className="cmanager-subtitle">
        {openScenarioRecord
          ? t('scenarios.detail_subtitle')
          : t('scenarios.list_subtitle')}
      </p>

      {workplacesError && <div className="cmanager-banner">{t('competences.load_error')}</div>}

      {openScenarioRecord ? (
        <section className="cmanager-panel">
          <header className="cmanager-panel-head cmanager-detail-head">
            <button type="button" className="cmanager-back" onClick={closeScenario}>
              ← {t('scenarios.back')}
            </button>
            <h2>
              {openScenarioRecord.name}
              {openScenarioRecord.is_selected && (
                <span className="cmanager-badge">{t('scenarios.active_badge')}</span>
              )}
            </h2>
            <span className="cmanager-detail-workplace">{selected?.name}</span>
          </header>

          <div className="cmanager-new">
            <button
              type="button"
              className="cmanager-btn cmanager-btn-primary"
              onClick={() => setEditorTarget('new')}
            >
              + {t('competences.add_competence')}
            </button>
          </div>

          {competencesLoading && <p className="cmanager-note">{t('departments.loading')}</p>}

          {!competencesLoading && sortedCompetences.length === 0 && (
            <p className="cmanager-note">{t('competences.empty')}</p>
          )}

          {sortedCompetences.length > 0 && (
            <table className="cmanager-table">
              <thead>
                <tr>
                  <th className="cmanager-col-name">{t('competence_manager.name')}</th>
                  <th>{t('competences.required_count')}</th>
                  <th>{t('scenarios.recovery_column')}</th>
                  <th className="cmanager-col-actions" />
                </tr>
              </thead>
              <tbody>
                {sortedCompetences.map((row) => (
                  <tr key={row.id}>
                    <td className="cmanager-col-name">
                      <button
                        type="button"
                        className="cmanager-link"
                        onClick={() => setEditorTarget(row)}
                      >
                        {row.name}
                      </button>
                      {row.description && (
                        <span className="cmanager-desc">{row.description}</span>
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
                            <b>{row.week[weekday].required_count}</b>
                          </span>
                        ))}
                      </div>
                    </td>

                    <td>
                      <div className="cmanager-week" aria-label={t('scenarios.recovery_column')}>
                        {ISO_WEEKDAYS.map((weekday) => (
                          <span
                            key={weekday}
                            className={`cmanager-day ${weekday >= 5 ? 'is-weekend' : ''}`}
                          >
                            <em>{t(`workload.days.${weekday}`)}</em>
                            <b>{clampRecoveryDays(row.week[weekday].recovery_days)}</b>
                          </span>
                        ))}
                      </div>
                    </td>

                    <td className="cmanager-col-actions">
                      <button
                        type="button"
                        className="cmanager-btn"
                        onClick={() => setEditorTarget(row)}
                      >
                        {t('competence_manager.edit')}
                      </button>
                      <button
                        type="button"
                        className="cmanager-btn cmanager-btn-danger"
                        title={t('competences.delete_hint')}
                        onClick={() => setDeleteCompetenceTarget(row)}
                      >
                        {t('competences.delete')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <p className="cmanager-hint">{t('scenarios.shared_competences_hint')}</p>
        </section>
      ) : (
        <section className="cmanager-panel">
          <header className="cmanager-panel-head">
            <h2>{selected?.name}</h2>
          </header>

          <form className="cmanager-new" onSubmit={handleCreateScenario}>
            <input
              className="cmanager-input"
              value={newScenarioName}
              onChange={(e) => setNewScenarioName(e.target.value)}
              placeholder={t('scenarios.new_placeholder')}
              aria-label={t('scenarios.name')}
            />
            <button
              type="submit"
              className="cmanager-btn cmanager-btn-primary"
              disabled={creatingScenario}
            >
              + {t('scenarios.add')}
            </button>
          </form>

          {scenariosLoading && <p className="cmanager-note">{t('departments.loading')}</p>}

          {!scenariosLoading && scenarios.length === 0 && (
            <p className="cmanager-note">{t('scenarios.empty')}</p>
          )}

          {scenarios.length > 0 && (
            <table className="cmanager-table">
              <thead>
                <tr>
                  <th className="cmanager-col-radio">{t('scenarios.active_column')}</th>
                  <th className="cmanager-col-name">{t('scenarios.name')}</th>
                  <th>{t('scenarios.competence_count')}</th>
                  <th className="cmanager-col-actions" />
                </tr>
              </thead>
              <tbody>
                {scenarios.map((scenario) => {
                  const isRenaming = renaming?.id === scenario.id;
                  return (
                    <tr key={scenario.id} className={scenario.is_selected ? 'is-selected' : ''}>
                      <td className="cmanager-col-radio">
                        <input
                          type="radio"
                          name="active-scenario"
                          checked={!!scenario.is_selected}
                          onChange={() => handleSelectScenario(scenario)}
                          aria-label={t('scenarios.select_named', { name: scenario.name })}
                        />
                      </td>

                      <td className="cmanager-col-name">
                        {isRenaming ? (
                          <input
                            className="cmanager-input"
                            value={renaming.name}
                            autoFocus
                            onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
                            aria-label={t('scenarios.name')}
                          />
                        ) : (
                          <button
                            type="button"
                            className="cmanager-link"
                            onClick={() => openScenario(scenario)}
                          >
                            {scenario.name}
                          </button>
                        )}
                      </td>

                      <td>{scenario.competence_count}</td>

                      <td className="cmanager-col-actions">
                        {isRenaming ? (
                          <>
                            <button
                              type="button"
                              className="cmanager-btn cmanager-btn-primary"
                              disabled={!renaming.name.trim()}
                              onClick={handleSaveRename}
                            >
                              {t('departments.save')}
                            </button>
                            <button
                              type="button"
                              className="cmanager-btn"
                              onClick={() => setRenaming(null)}
                            >
                              {t('departments.cancel')}
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="cmanager-btn"
                              onClick={() => openScenario(scenario)}
                            >
                              {t('scenarios.open')}
                            </button>
                            <button
                              type="button"
                              className="cmanager-btn"
                              onClick={() =>
                                setRenaming({ id: scenario.id, name: scenario.name })
                              }
                            >
                              {t('scenarios.rename')}
                            </button>
                            <button
                              type="button"
                              className="cmanager-btn cmanager-btn-danger"
                              disabled={scenarios.length < 2}
                              title={
                                scenarios.length < 2
                                  ? t('scenarios.delete_last_hint')
                                  : t('scenarios.delete_hint')
                              }
                              onClick={() => setDeleteScenarioTarget(scenario)}
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

          <p className="cmanager-hint">{t('scenarios.list_hint')}</p>
        </section>
      )}

      {toast && (
        <div className="cmanager-toast" role="status">
          {toast}
        </div>
      )}

      <CompetenceEditorDialog
        key={editorTarget === 'new' ? 'new' : (editorTarget?.id ?? 'closed')}
        open={!!editorTarget}
        competence={editorTarget === 'new' ? null : editorTarget}
        saving={savingCompetence}
        onSave={handleSaveCompetence}
        onCancel={() => setEditorTarget(null)}
      />

      <ConfirmDialog
        open={!!deleteScenarioTarget}
        message={t('scenarios.confirm_delete_named', { name: deleteScenarioTarget?.name })}
        confirmLabel={t('competences.delete')}
        cancelLabel={t('departments.cancel')}
        onConfirm={handleDeleteScenario}
        onCancel={() => setDeleteScenarioTarget(null)}
      />

      <ConfirmDialog
        open={!!deleteCompetenceTarget}
        message={t('scenarios.confirm_delete_competence', {
          name: deleteCompetenceTarget?.name,
        })}
        confirmLabel={t('competences.delete')}
        cancelLabel={t('departments.cancel')}
        onConfirm={handleDeleteCompetence}
        onCancel={() => setDeleteCompetenceTarget(null)}
      />
    </div>
  );
};

export default CompetenceManagerView;
