import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { ChevronLeftIcon, PlusIcon, TrashIcon } from '../components/NavIcons';
import Toast from '../components/Toast';
import { useToast } from '../hooks/useToast';
import {
  REQUIREMENT_SLOTS,
  SPECIAL_DAY_SLOT,
  clampRecoveryDays,
  clampShiftHours,
  normalizeCompetenceRequirements,
  normalizeWeekdayRequirements,
} from '../utils/competenceRequirements';
import './CompetenceManagerView.css';

/** Whether a slot is the day of rest rather than one of the seven weekdays.
 *  A public holiday is staffed from that slot whatever weekday it falls on;
 *  which dates those are is what the Special days screen decides. */
const isSpecialDay = (slot) => Number(slot) === SPECIAL_DAY_SLOT;

/** Heading for one slot: a weekday's short name, or the day-of-rest mark. */
const slotLabel = (t, slot) =>
  isSpecialDay(slot) ? t('special_days.column_short') : t(`workload.days.${slot}`);

/** One day chip of a week strip: weekends are shaded, the day of rest is
 *  fenced off from the week, and a day paid with a surcharge is ringed, so a
 *  surcharged day is visible without reading a column of labels. */
const dayClassName = (dayParameters, weekday) =>
  [
    'cmanager-day',
    weekday >= 5 && weekday <= 6 ? 'is-weekend' : '',
    isSpecialDay(weekday) ? 'is-special' : '',
    dayParameters.is_surcharge ? 'is-surcharge' : '',
  ]
    .join(' ')
    .trim();

/** Place the key beside the pointer, flipping it to the other side or
 *  above once it would otherwise run off the window. The size is the
 *  card's own worst case, which is cheaper than measuring it every time
 *  the mouse moves by a pixel. */
const LEGEND_SIZE = { width: 260, height: 148 };
const LEGEND_GAP = 16;

const legendPosition = (event) => {
  const { clientX, clientY } = event;
  const room = LEGEND_GAP + LEGEND_SIZE.width < window.innerWidth - clientX;
  const below = LEGEND_GAP + LEGEND_SIZE.height < window.innerHeight - clientY;
  return {
    left: room ? clientX + LEGEND_GAP : clientX - LEGEND_GAP - LEGEND_SIZE.width,
    top: below ? clientY + LEGEND_GAP : clientY - LEGEND_GAP - LEGEND_SIZE.height,
  };
};

/**
 * Competence scenarios of one workplace (scheduler screen).
 *
 * The screen has two modes and swaps between them in place, without a
 * route change: a list of the workplace's scenarios — with the active
 * one's competences spelled out underneath, since that is the table the
 * rest of the application is scheduled from — and one scenario opened for
 * editing. Editing a single competence happens in a modal on
 * top of the second mode.
 *
 * The competence list itself is workplace-wide — the same three or four
 * competences exist in every scenario. What a scenario owns is their
 * parameters: how many people each one needs on each weekday, and how much
 * recovery a duty costs. Exactly one scenario is selected, and that is the
 * one the schedule generator and the other screens read; the rest are
 * model cases kept side by side.
 *
 * Clicking a scenario row puts that scenario in the table on the right;
 * which scenario is *active* -- the one the generator reads -- is the
 * radio, and the two are deliberately separate, so a model case can be
 * read and edited without scheduling anything from it. A double-click on
 * the name renames instead (F2 does the same from the keyboard), and that
 * rename behaves the way renaming a file does: Enter or clicking away
 * keeps the new name, Escape drops it.
 *
 * Every action here hits the backend right away — these are registry
 * writes, not a draft — so the screen has no dirty state and no save
 * button outside the modal.
 */
/** The per-scenario detail screen is hidden for now: the summary card on
 *  the list does the same work without the extra hop. The screen itself is
 *  kept intact behind this switch, so turning it back on is one line. */
const SCENARIO_DETAIL_ENABLED = false;

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
  const [overview, setOverview] = useState([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  // Where to draw the key, in viewport coordinates, or null while the
  // pointer is away from the table.
  const [legendAt, setLegendAt] = useState(null);
  const [viewedId, setViewedId] = useState(null);

  const [toast, notify] = useToast();
  const [creatingScenario, setCreatingScenario] = useState(false);
  const [duplicatingId, setDuplicatingId] = useState(null);
  const [renaming, setRenaming] = useState(null); // { id, name }
  const [editorTarget, setEditorTarget] = useState(null); // competence | 'new'
  const [savingCompetence, setSavingCompetence] = useState(false);
  const [deleteScenarioTarget, setDeleteScenarioTarget] = useState(null);
  const [deleteCompetenceTarget, setDeleteCompetenceTarget] = useState(null);

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
  }, [selectedId, t, notify]);

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
    setViewedId(null);
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
    [selectedId, t, notify]
  );

  const activeScenario = useMemo(
    () => scenarios.find((item) => item.is_selected) || null,
    [scenarios]
  );

  // Nothing clicked yet, or a scenario that has since been deleted, falls
  // back to the active one -- the table is never empty for want of a
  // choice, and it opens on what the workplace is scheduled from.
  const viewedScenario = useMemo(
    () => scenarios.find((item) => item.id === viewedId) || activeScenario,
    [scenarios, viewedId, activeScenario]
  );

  const viewedScenarioId = viewedScenario?.id ?? null;

  // Clicking through the scenario list fires one request per click; only
  // the last one may fill the table, or a slow answer for the scenario
  // clicked before would show under the one clicked after.
  const overviewSeq = useRef(0);

  const loadOverview = useCallback(async () => {
    const seq = ++overviewSeq.current;
    if (selectedId == null || viewedScenarioId == null) {
      setOverview([]);
      return;
    }
    setOverviewLoading(true);
    try {
      const rows = await fetchScenarioCompetences(selectedId, viewedScenarioId);
      if (seq === overviewSeq.current) setOverview(rows.map(normalizeCompetenceRequirements));
    } catch {
      if (seq === overviewSeq.current) setOverview([]);
    } finally {
      if (seq === overviewSeq.current) setOverviewLoading(false);
    }
  }, [selectedId, viewedScenarioId]);

  useEffect(() => {
    loadOverview();
  }, [loadOverview, openScenarioId]);

  // Held long enough that the second click of a double-click arrives
  // first; a rename then cancels the pending open.
  const OPEN_CLICK_DELAY_MS = 220;
  const openTimer = useRef(null);

  const cancelPendingOpen = () => {
    clearTimeout(openTimer.current);
    openTimer.current = null;
  };

  useEffect(() => cancelPendingOpen, []);

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

  const handleCreateScenario = async () => {
    if (creatingScenario || selectedId == null) return;
    const name = nextScenarioName();
    setCreatingScenario(true);
    try {
      // A new scenario covers the same competences with the defaults --
      // one person, four hours, one recovery day. Starting from the active
      // one's numbers is what Duplicate is for.
      const created = await createScenario(selectedId, name, null);
      setScenarios((prev) => [...prev, created]);
      setViewedId(created.id);
      notify(t('scenarios.added'));
    } catch {
      notify(t('competences.action_error'));
    } finally {
      setCreatingScenario(false);
    }
  };

  /** First free name of the form "X (copy)", "X (copy 2)", ... */
  const copyName = (scenario) => {
    const used = new Set(scenarios.map((item) => item.name));
    const base = t('scenarios.copy_name', { name: scenario.name });
    if (!used.has(base)) return base;
    let index = 2;
    while (used.has(`${base} ${index}`)) index += 1;
    return `${base} ${index}`;
  };

  // A duplicate is an ordinary create seeded from the chosen scenario
  // rather than from the active one, so the copy is exact and unselected.
  const handleDuplicateScenario = async (scenario) => {
    if (duplicatingId != null || selectedId == null) return;
    setDuplicatingId(scenario.id);
    try {
      const created = await createScenario(
        selectedId,
        copyName(scenario),
        scenario.id
      );
      setScenarios((prev) => [...prev, created]);
      setViewedId(created.id);
      notify(t('scenarios.duplicated'));
    } catch {
      notify(t('competences.action_error'));
    } finally {
      setDuplicatingId(null);
    }
  };

  const scheduleOpen = (scenario) => {
    if (!SCENARIO_DETAIL_ENABLED) return;
    cancelPendingOpen();
    openTimer.current = setTimeout(() => {
      openTimer.current = null;
      openScenario(scenario);
    }, OPEN_CLICK_DELAY_MS);
  };

  /** Controls that own their own click: the rename field and the row's
   *  action buttons. The name is deliberately not among them --
   *  it is part of the row and behaves like the rest of it. */
  const isOwnControl = (event) =>
    !!event.target.closest('input, label, .btn');

  const handleRowClick = (event, scenario) => {
    if (isOwnControl(event)) return;
    if (renaming?.id === scenario.id) return;
    setViewedId(scenario.id);
    scheduleOpen(scenario);
  };

  /** Anywhere on the row, not only on the name: a double click is how the
   *  row is renamed, and hunting for the one word that accepts it is not
   *  a gesture anyone would guess. */
  const handleRowDoubleClick = (event, scenario) => {
    if (isOwnControl(event)) return;
    handleRenameGesture(scenario);
  };

  const handleRenameGesture = (scenario) => {
    cancelPendingOpen();
    setRenaming({ id: scenario.id, name: scenario.name });
  };

  /** F2 renames from the keyboard, as it does in a file manager. */
  const handleNameKeyDown = (event, scenario) => {
    if (event.key !== 'F2') return;
    event.preventDefault();
    handleRenameGesture(scenario);
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

  // Escape has to beat the blur that follows it, or leaving the field
  // would save the name the user just abandoned.
  const abandonRename = useRef(false);

  const cancelRename = () => {
    abandonRename.current = true;
    setRenaming(null);
  };

  /** Leaving the field keeps the new name; an empty or unchanged one is
   *  simply the end of the rename, not an error to complain about. */
  const handleSaveRename = async () => {
    if (!renaming) return;
    const target = scenarios.find((item) => item.id === renaming.id);
    const name = renaming.name.trim();
    setRenaming(null);
    if (!name || name === target?.name) return;
    try {
      const updated = await updateScenario(selectedId, renaming.id, { name });
      setScenarios((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      notify(t('scenarios.renamed'));
    } catch {
      notify(t('competences.action_error'));
    }
  };

  const handleRenameBlur = () => {
    if (abandonRename.current) {
      abandonRename.current = false;
      return;
    }
    handleSaveRename();
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

  // The editor is reachable from the open scenario and from the card, so
  // the numbers land in whichever scenario the screen is showing.
  const editedScenarioId = openScenarioId ?? viewedScenarioId;

  const handleSaveCompetence = async (payload) => {
    if (savingCompetence || editedScenarioId == null) return;
    setSavingCompetence(true);
    try {
      if (editorTarget === 'new') {
        const created = normalizeCompetenceRequirements(
          await createScenarioCompetence(selectedId, editedScenarioId, payload)
        );
        if (openScenarioId != null) setCompetences((prev) => [...prev, created]);
        notify(t('competences.added'));
        loadScenarios();
      } else {
        const updated = normalizeCompetenceRequirements(
          await updateScenarioCompetence(
            selectedId,
            editedScenarioId,
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
      loadOverview();
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
      await deleteScenarioCompetence(selectedId, editedScenarioId, target.id);
      setCompetences((prev) => prev.filter((item) => item.id !== target.id));
      notify(t('competences.deleted'));
      loadScenarios();
      loadOverview();
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

  const overviewRows = [...overview]
    .map((competence) => ({
      ...competence,
      week: normalizeWeekdayRequirements(competence),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));

  if (loading) {
    return (
      <div className="page cmanager">
        <p className="cmanager-state">
          <span className="spinner" aria-hidden="true" />
          {t('departments.loading')}
        </p>
      </div>
    );
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="page cmanager">
        <header className="page-header">
          <h1 className="page-title">{t('competence_manager.title')}</h1>
        </header>
        <div className="alert alert-info">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const sortedCompetences = [...rows].sort((a, b) => a.name.localeCompare(b.name));

  /** Title of one slot's figures: the day of rest explains itself, a
   *  surcharged day says so. */
  const slotTitle = (week, weekday) =>
    isSpecialDay(weekday)
      ? t('special_days.column_hint')
      : week[weekday].is_surcharge
        ? t('scenarios.surcharge_day_hint')
        : undefined;

  /** The key to the summary table: what the three figures of a cell are,
   *  what the ring means and what the eighth column is. */
  const legendItems = (
    <>
      <span className="cmanager-legend-item">
        <b>1</b>
        {t('scenarios.legend_count')}
      </span>
      <span className="cmanager-legend-item">
        <em>4 h</em>
        {t('scenarios.legend_hours')}
      </span>
      <span className="cmanager-legend-item">
        <em>1 d</em>
        {t('scenarios.legend_recovery')}
      </span>
      <span className="cmanager-legend-item">
        <i className="cmanager-legend-frame" aria-hidden="true" />
        {t('scenarios.legend_surcharge')}
      </span>
      <span className="cmanager-legend-item">
        <b className="is-special">{t('special_days.column_short')}</b>
        {t('special_days.legend')}
      </span>
    </>
  );

  return (
    <div className="page cmanager">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('competence_manager.title')}</h1>
          {selected && (
            <p className="page-subtitle">
              <span className="cmanager-workplace">{selected.name}</span>
            </p>
          )}
        </div>
      </header>

      {workplacesError && (
        <div className="alert alert-danger cmanager-alert" role="alert">
          {t('competences.load_error')}
        </div>
      )}

      {openScenarioRecord ? (
        <section className="card cmanager-panel">
          <header className="card-header cmanager-detail-head">
            <button type="button" className="btn btn-ghost btn-sm" onClick={closeScenario}>
              <ChevronLeftIcon />
              {t('scenarios.back')}
            </button>
            <h2 className="card-title cmanager-detail-title">
              {openScenarioRecord.name}
              {openScenarioRecord.is_selected && (
                <span className="badge badge-primary">{t('scenarios.active_badge')}</span>
              )}
            </h2>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => setEditorTarget('new')}
            >
              <PlusIcon />
              {t('competences.add_competence')}
            </button>
          </header>

          {competencesLoading && (
            <p className="cmanager-note">
              <span className="spinner" aria-hidden="true" />
              {t('departments.loading')}
            </p>
          )}

          {!competencesLoading && (
            <div className="cmanager-scroll">
              <table className="data-table cmanager-table">
                <thead>
                  <tr>
                    <th className="cmanager-col-name">{t('competence_manager.name')}</th>
                    <th>{t('competences.required_count')}</th>
                    <th>{t('scenarios.hours_column')}</th>
                    <th>{t('scenarios.recovery_column')}</th>
                    <th className="cmanager-col-actions" />
                  </tr>
                </thead>
                <tbody>
                  {sortedCompetences.length === 0 && (
                    <tr>
                      <td className="cmanager-empty-row" colSpan={5}>
                        {t('competences.empty')}
                      </td>
                    </tr>
                  )}
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

                      {[
                        {
                          label: t('competences.required_count'),
                          value: (item) => item.required_count,
                        },
                        {
                          label: t('scenarios.hours_column'),
                          value: (item) => clampShiftHours(item.shift_hours),
                        },
                        {
                          label: t('scenarios.recovery_column'),
                          value: (item) => clampRecoveryDays(item.recovery_days),
                        },
                      ].map((strip) => (
                        <td key={strip.label}>
                          <div className="cmanager-week" aria-label={strip.label}>
                            {REQUIREMENT_SLOTS.map((weekday) => (
                              <span
                                key={weekday}
                                className={dayClassName(row.week[weekday], weekday)}
                                title={slotTitle(row.week, weekday)}
                              >
                                <em>{slotLabel(t, weekday)}</em>
                                <b>{strip.value(row.week[weekday])}</b>
                              </span>
                            ))}
                          </div>
                        </td>
                      ))}

                      <td className="cmanager-col-actions">
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => setEditorTarget(row)}
                        >
                          {t('competence_manager.edit')}
                        </button>
                        <button
                          type="button"
                          className="btn btn-sm btn-danger-outline"
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
            </div>
          )}
        </section>
      ) : (
        <div className="cmanager-columns">
          <section className="card cmanager-scenarios">
            <header className="card-header">
              <h2 className="card-title">{t('scenarios.title')}</h2>
              <button
                type="button"
                className="btn btn-sm btn-secondary"
                disabled={creatingScenario}
                onClick={handleCreateScenario}
              >
                <PlusIcon />
                {t('scenarios.add')}
              </button>
            </header>

            {scenariosLoading && scenarios.length === 0 && (
              <p className="cmanager-note">
                <span className="spinner" aria-hidden="true" />
                {t('departments.loading')}
              </p>
            )}

            {!scenariosLoading && scenarios.length === 0 && (
              <p className="cmanager-note">{t('scenarios.empty')}</p>
            )}

            {scenarios.length > 0 && (
              <table className="data-table cmanager-table cmanager-scenario-table">
                <thead>
                  <tr>
                    <th className="cmanager-col-name">{t('scenarios.name')}</th>
                    <th className="cmanager-col-actions">
                      <span className="visually-hidden">{t('scenarios.duplicate')}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.map((scenario) => {
                    const isRenaming = renaming?.id === scenario.id;
                    const isViewed = scenario.id === viewedScenario?.id;
                    return (
                      <tr
                        key={scenario.id}
                        className={[
                          'cmanager-row',
                          'is-openable',
                          isViewed ? 'is-viewed' : '',
                          scenario.is_selected ? 'is-selected' : '',
                        ]
                          .join(' ')
                          .trim()}
                        aria-current={isViewed || undefined}
                        title={t('scenarios.rename_hint')}
                        onClick={(e) => handleRowClick(e, scenario)}
                        onDoubleClick={(e) => handleRowDoubleClick(e, scenario)}
                      >
                        <td className="cmanager-col-name">
                          {isRenaming ? (
                            <input
                              className="input input-sm cmanager-rename"
                              value={renaming.name}
                              autoFocus
                              onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') e.target.blur();
                                if (e.key === 'Escape') cancelRename();
                              }}
                              onBlur={handleRenameBlur}
                              aria-label={t('scenarios.name')}
                            />
                          ) : (
                            /* Not a control of its own -- the click and the
                               double click belong to the row -- but a button
                               all the same, so the keyboard can reach it:
                               Enter shows the scenario, F2 renames it. */
                            <button
                              type="button"
                              className="cmanager-name"
                              aria-pressed={isViewed}
                              onKeyDown={(e) => handleNameKeyDown(e, scenario)}
                            >
                              {scenario.name}
                            </button>
                          )}
                          {scenario.is_selected && !isRenaming && (
                            <span className="badge badge-primary cmanager-active-badge">
                              {t('scenarios.active_badge')}
                            </span>
                          )}
                        </td>

                        <td className="cmanager-col-actions">
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost"
                            disabled={duplicatingId != null}
                            title={t('scenarios.duplicate_hint')}
                            onClick={() => handleDuplicateScenario(scenario)}
                          >
                            {t('scenarios.duplicate')}
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost btn-icon cmanager-delete"
                            disabled={scenarios.length < 2}
                            aria-label={`${t('scenarios.delete_hint')}: ${scenario.name}`}
                            title={
                              scenarios.length < 2
                                ? t('scenarios.delete_last_hint')
                                : t('scenarios.delete_hint')
                            }
                            onClick={() => setDeleteScenarioTarget(scenario)}
                          >
                            <TrashIcon />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </section>

          {viewedScenario && (
            <section className="card cmanager-summary">
              <header className="card-header">
                {/* Keyed by scenario so the heading replays its entrance on
                    every switch -- the one cue that the table changed. */}
                <div className="cmanager-summary-heading" key={viewedScenario.id}>
                  <h2 className="card-title">{viewedScenario.name}</h2>
                  {viewedScenario.is_selected ? (
                    <span className="badge badge-primary">{t('scenarios.active_badge')}</span>
                  ) : (
                    <span className="badge">{t('scenarios.inactive_badge')}</span>
                  )}
                </div>
                <div className="cmanager-summary-actions">
                  {!viewedScenario.is_selected && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => handleSelectScenario(viewedScenario)}
                    >
                      {t('scenarios.make_active')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-sm btn-secondary"
                    onClick={() => setEditorTarget('new')}
                  >
                    <PlusIcon />
                    {t('competences.add_competence')}
                  </button>
                </div>
              </header>
              {/* Held back until the table is actually being read: the three
                  figures stacked in a cell and the frame around a day are
                  not self-evident, but a permanent key beside them was what
                  pushed the seven weekday columns out of shape. It rides
                  with the pointer, so the answer is wherever the question
                  was asked. Touch screens have no pointer to ride with, so
                  they get the same key under the table instead. */}
              {legendAt && (
                <div className="cmanager-legend" role="note" style={legendAt}>
                  {legendItems}
                </div>
              )}
              <div
                className={`cmanager-summary-scroll ${overviewLoading ? 'is-loading' : ''}`.trim()}
                aria-busy={overviewLoading || undefined}
              >
                <table
                  className="cmanager-summary-table"
                  onMouseMove={(e) => setLegendAt(legendPosition(e))}
                  onMouseLeave={() => setLegendAt(null)}
                >
                  <thead>
                    <tr>
                      <th className="cmanager-col-name">
                        {t('competence_manager.name')}
                      </th>
                      {REQUIREMENT_SLOTS.map((weekday) => (
                        <th
                          key={weekday}
                          className={[
                            weekday >= 5 && weekday <= 6 ? 'is-weekend' : '',
                            isSpecialDay(weekday) ? 'is-special' : '',
                          ]
                            .join(' ')
                            .trim()}
                          title={
                            isSpecialDay(weekday)
                              ? t('special_days.column_hint')
                              : undefined
                          }
                        >
                          {slotLabel(t, weekday)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {overviewRows.length === 0 && (
                      <tr>
                        <td className="cmanager-empty-row" colSpan={REQUIREMENT_SLOTS.length + 1}>
                          {t('competences.empty')}
                        </td>
                      </tr>
                    )}
                    {overviewRows.map((row) => (
                      <tr
                        key={row.id}
                        className="cmanager-row is-openable"
                        title={t('competence_manager.edit')}
                        onClick={(e) => {
                          // The delete cross is the row's one other control;
                          // the name is a button so the keyboard can open
                          // the editor, and its click is the row's click.
                          if (e.target.closest('.cmanager-summary-delete')) return;
                          setEditorTarget(row);
                        }}
                      >
                        <td className="cmanager-col-name">
                          <div className="cmanager-summary-name">
                            <button type="button" className="cmanager-link">
                              {row.name}
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-icon btn-sm cmanager-delete cmanager-summary-delete"
                              aria-label={`${t('competences.delete_hint')}: ${row.name}`}
                              title={t('competences.delete_hint')}
                              onClick={() => setDeleteCompetenceTarget(row)}
                            >
                              <TrashIcon />
                            </button>
                          </div>
                        </td>
                        {REQUIREMENT_SLOTS.map((weekday) => (
                          <td
                            key={weekday}
                            className={[
                              'cmanager-summary-cell',
                              weekday >= 5 && weekday <= 6 ? 'is-weekend' : '',
                              isSpecialDay(weekday) ? 'is-special' : '',
                              row.week[weekday].is_surcharge ? 'is-surcharge' : '',
                            ]
                              .join(' ')
                              .trim()}
                            title={slotTitle(row.week, weekday)}
                          >
                            <span className="cmanager-summary-figures">
                              <b>{row.week[weekday].required_count}</b>
                              <em>
                                {t('scenarios.hours_short', {
                                  hours: clampShiftHours(row.week[weekday].shift_hours),
                                })}
                              </em>
                              <em>
                                {t('scenarios.recovery_short', {
                                  days: clampRecoveryDays(row.week[weekday].recovery_days),
                                })}
                              </em>
                            </span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="cmanager-legend-static" role="note">
                {legendItems}
              </div>
            </section>
          )}
        </div>
      )}

      <Toast message={toast} />

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
        title={t('scenarios.delete_hint')}
        message={t('scenarios.confirm_delete_named', { name: deleteScenarioTarget?.name })}
        confirmLabel={t('competences.delete')}
        cancelLabel={t('departments.cancel')}
        tone="danger"
        onConfirm={handleDeleteScenario}
        onCancel={() => setDeleteScenarioTarget(null)}
      />

      <ConfirmDialog
        open={!!deleteCompetenceTarget}
        title={t('competences.delete_hint')}
        message={t('scenarios.confirm_delete_competence', {
          name: deleteCompetenceTarget?.name,
        })}
        confirmLabel={t('competences.delete')}
        cancelLabel={t('departments.cancel')}
        tone="danger"
        onConfirm={handleDeleteCompetence}
        onCancel={() => setDeleteCompetenceTarget(null)}
      />
    </div>
  );
};

export default CompetenceManagerView;
