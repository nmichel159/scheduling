import { useState, useMemo, useRef, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { requiredCountForGroup } from '../utils/competenceRequirements';
import './CompetenceMatrix.css';

/**
 * Presentational employee x competence table for one ambulance.
 *
 * All draft state (rows, columns, dirty tracking, persistence) lives in
 * the parent (DepartmentsView) — this component only renders it and
 * reports interactions via callbacks. It does not call the backend
 * itself, except by delegating to the two codebook callbacks below,
 * which the parent resolves immediately (adding/removing a competence
 * definition is a registry write, not part of the editable draft).
 *
 * Each employee x competence cell is a single binary toggle for the
 * whole week — a person either holds the competence in this ambulance
 * or doesn't; there is no per-weekday breakdown here (that's what
 * `onToggleWeek` flips). The whole cell area is clickable (not just a
 * small inner square) — see .cmatrix-daycell in the CSS.
 *
 * The "Potrebný počet" header rows show, per day-group (e.g. Po–Pi vs
 * So–Ne), how many people with that competence the ambulance needs on
 * those days. The ✎ pencil next to the day-chips splits a group into a
 * finer day range with its own required count.
 *
 * Props:
 * - columns: [{ id, name, description }] — competences of the ambulance
 * - rows: [{ user_id, email, full_name, competenceDays: { [competenceId]: number[] } }] — draft state.
 *   competenceDays[competenceId] holds the ISO weekdays (0=Po..6=Ne) on which
 *   that employee holds that competence; a missing/empty entry means "not assigned".
 *   This view only ever sets it to "all 7 days" or empty (see onToggleWeek).
 * - allUsers: [{ id, email, full_name }] — hospital-wide pool for the search box
 * - loading: table is (re)loading
 * - onToggleWeek(userId, competenceId) — assign/clear the competence for the whole week
 * - onAddRow(user)
 * - onRemoveRow(userId)
 * - onAddCompetence(name): Promise
 * - onUpdateRequiredCount(groupId, competenceId, requiredCount) — draft-only;
 *   the parent only commits this to the backend when the shared "Uložiť"
 *   button is clicked, same as every other edit in this table.
 * - onSplitRequirementDays(groupId, weekdays)
 * - onDeleteCompetence(competenceId): Promise
 */
const CompetenceMatrix = ({
  columns,
  dayGroups,
  rows,
  allUsers,
  loading,
  onToggleWeek,
  onAddRow,
  onRemoveRow,
  onAddCompetence,
  onUpdateRequiredCount,
  onSplitRequirementDays,
  onDeleteCompetence,
}) => {
  const { t } = useTranslation();

  const [search, setSearch] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [addingCompetence, setAddingCompetence] = useState(false);
  const [newCompetenceName, setNewCompetenceName] = useState('');
  const [deletingId, setDeletingId] = useState(null);
  const [removingRowId, setRemovingRowId] = useState(null);

  /* ---------- required head-count row (per competence) ----------
   * Shows how many employees each competence needs in this ambulance.
   * The cell is green when the draft count matches the requirement exactly,
   * red otherwise. Hovering a cell reveals a pencil icon (left edge);
   * clicking it opens an inline stepper with ▲/▼ arrows. Changes are
   * local draft only — they are saved together with all other edits when
   * the user clicks the shared "Uložiť" button.
   */
  const requiredOf = (col, group) => requiredCountForGroup(col, group);

  const [splittingGroupId, setSplittingGroupId] = useState(null);
  const [selectedSplitDays, setSelectedSplitDays] = useState([]);

  const stepRequired = (group, col, delta) => {
    const next = Math.max(0, requiredOf(col, group) + delta);
    onUpdateRequiredCount(group.id, col.id, next);
  };

  const openSplitDays = (group) => {
    setSplittingGroupId(group.id);
    setSelectedSplitDays([]);
  };

  const toggleSplitDay = (weekday) => {
    setSelectedSplitDays((previous) =>
      previous.includes(weekday)
        ? previous.filter((item) => item !== weekday)
        : [...previous, weekday].sort((a, b) => a - b)
    );
  };

  const confirmSplitDays = () => {
    if (!splittingGroupId) return;
    onSplitRequirementDays(splittingGroupId, selectedSplitDays);
    setSplittingGroupId(null);
    setSelectedSplitDays([]);
  };

  /* ---------- employee search (add row) ----------
   * The dropdown opens on focus with the full list of assignable users
   * (everyone not already in the table) and narrows as the user types.
   */

  const searchResults = useMemo(() => {
    const q = search.trim().toLowerCase();
    const present = new Set(rows.map((r) => r.user_id));
    const available = allUsers.filter((u) => !present.has(u.id));
    if (!q) return available;
    return available.filter(
      (u) =>
        u.email.toLowerCase().includes(q) ||
        (u.full_name || '').toLowerCase().includes(q)
    );
  }, [search, allUsers, rows]);

  const handlePick = (user) => {
    onAddRow(user);
    setSearch('');
  };

  /* ---------- floating layers (dropdown + popover) ----------
   * .cmatrix-scroll needs overflow-x:auto for wide tables, but the CSS
   * overflow spec forces overflow-y to 'auto' too whenever overflow-x
   * isn't 'visible' — so any position:absolute layer nested inside it
   * gets silently clipped once it grows taller than the scroll box.
   * Portaling to <body> and positioning from a measured rect sidesteps
   * that entirely.
   */
  const searchAnchorRef = useRef(null);
  const suggestElRef = useRef(null);
  const [suggestRect, setSuggestRect] = useState(null);

  useLayoutEffect(() => {
    if (!searchOpen || !searchAnchorRef.current) return;
    const el = searchAnchorRef.current;
    const update = () => setSuggestRect(el.getBoundingClientRect());
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);

    const handleMouseDown = (e) => {
      if (
        !el.contains(e.target) &&
        !(suggestElRef.current && suggestElRef.current.contains(e.target))
      ) {
        setSearchOpen(false);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setSearchOpen(false);
    };
    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [searchOpen]);

  const popoverAnchorRef = useRef(null);
  const popoverElRef = useRef(null);
  const [popoverRect, setPopoverRect] = useState(null);

  useLayoutEffect(() => {
    if (!removingRowId || !popoverAnchorRef.current) return;
    const anchor = popoverAnchorRef.current;
    const update = () => setPopoverRect(anchor.getBoundingClientRect());
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);

    const handleMouseDown = (e) => {
      if (
        !anchor.contains(e.target) &&
        !(popoverElRef.current && popoverElRef.current.contains(e.target))
      ) {
        setRemovingRowId(null);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setRemovingRowId(null);
    };
    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [removingRowId]);

  /* Competence-deletion confirm popover — same portal pattern. */
  const deleteAnchorRef = useRef(null);
  const deleteElRef = useRef(null);
  const [deleteRect, setDeleteRect] = useState(null);

  useLayoutEffect(() => {
    if (!deletingId || !deleteAnchorRef.current) return;
    const anchor = deleteAnchorRef.current;
    const update = () => setDeleteRect(anchor.getBoundingClientRect());
    update();
    window.addEventListener('scroll', update, true);
    window.addEventListener('resize', update);

    const handleMouseDown = (e) => {
      if (
        !anchor.contains(e.target) &&
        !(deleteElRef.current && deleteElRef.current.contains(e.target))
      ) {
        setDeletingId(null);
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setDeletingId(null);
    };
    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [deletingId]);

  /* ---------- codebook actions (immediate) ---------- */

  const handleAddCompetence = async () => {
    const name = newCompetenceName.trim();
    if (!name) return;
    await onAddCompetence(name);
    setNewCompetenceName('');
    setAddingCompetence(false);
  };

  const handleDeleteCompetence = async (competenceId) => {
    await onDeleteCompetence(competenceId);
    setDeletingId(null);
  };

  /* ---------- row removal (confirm) ---------- */

  const handleRemoveRow = (userId) => {
    onRemoveRow(userId);
    setRemovingRowId(null);
  };

  /* ---------- render ---------- */

  const competenceColSpan = Math.max(columns.length, 1);
  const removingRow = rows.find((r) => r.user_id === removingRowId) || null;
  const splittingGroup =
    dayGroups.find((group) => group.id === splittingGroupId) || null;
  const canConfirmSplit =
    splittingGroup &&
    selectedSplitDays.length > 0 &&
    selectedSplitDays.length < splittingGroup.weekdays.length;

  return (
    <section className="cmatrix">
      <div className={`cmatrix-scroll ${loading ? 'is-loading' : ''}`}>
        <table className="cmatrix-table">
          <thead>
            <tr className="cmatrix-group-row">
              <th className="cmatrix-corner">{t('competences.employee')}</th>
              <th className="cmatrix-group-header" colSpan={competenceColSpan}>
                <div className="cmatrix-group-inner">
                  <span className="cmatrix-group-title">{t('competences.title')}</span>
                  {addingCompetence ? (
                    <span className="cmatrix-add">
                      <input
                        type="text"
                        autoFocus
                        value={newCompetenceName}
                        onChange={(e) => setNewCompetenceName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleAddCompetence()}
                        placeholder={t('competences.new_placeholder')}
                        aria-label={t('competences.new_placeholder')}
                      />
                      <button
                        type="button"
                        className="departments-btn departments-btn-primary"
                        disabled={!newCompetenceName.trim()}
                        onClick={handleAddCompetence}
                      >
                        {t('departments.add')}
                      </button>
                      <button
                        type="button"
                        className="departments-btn"
                        onClick={() => {
                          setAddingCompetence(false);
                          setNewCompetenceName('');
                        }}
                      >
                        {t('departments.no')}
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="cmatrix-addcol-btn"
                      onClick={() => setAddingCompetence(true)}
                      aria-label={t('competences.add_competence')}
                      title={t('competences.add_competence')}
                    >
                      +
                    </button>
                  )}
                </div>
              </th>
            </tr>
            <tr>
              <th className="cmatrix-corner cmatrix-search-th">
                <div className="cmatrix-search" ref={searchAnchorRef}>
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onFocus={() => setSearchOpen(true)}
                    placeholder={t('competences.search_placeholder')}
                    aria-label={t('competences.search_placeholder')}
                  />
                </div>
              </th>
              {columns.map((c) => (
                <th key={c.id} className="cmatrix-col" title={c.description || c.name}>
                  <div className="cmatrix-col-inner">
                    <span className="cmatrix-colname">{c.name}</span>
                    <button
                      type="button"
                      className={`cmatrix-remove-btn ${deletingId === c.id ? 'is-active' : ''}`}
                      onClick={(e) => {
                        deleteAnchorRef.current = e.currentTarget;
                        setDeletingId(c.id);
                      }}
                      title={t('competences.delete_hint')}
                      aria-label={t('competences.delete_hint')}
                    >
                      ✕
                    </button>
                  </div>
                </th>
              ))}
            </tr>
            {columns.length > 0 && dayGroups.map((group, index) => (
              <tr
                className={`cmatrix-required-row ${index % 2 === 1 ? 'is-alt' : ''}`}
                key={group.id}
              >
                <th className="cmatrix-corner cmatrix-required-label">
                  <div className="cmatrix-required-label-inner">
                    <span className="cmatrix-day-chips">
                      {group.weekdays.map((weekday) => (
                        <span className="cmatrix-day-chip" key={weekday}>
                          {t(`workload.days.${weekday}`)}
                        </span>
                      ))}
                    </span>
                    {group.weekdays.length > 1 && (
                      <button
                        type="button"
                        className="cmatrix-split-days"
                        onClick={() => openSplitDays(group)}
                        title={t('competences.split_days')}
                        aria-label={t('competences.split_days')}
                      >
                        ✎
                      </button>
                    )}
                  </div>
                </th>
                {columns.map((c) => {
                  const required = requiredOf(c, group);
                  const assigned = rows.filter((r) =>
                    (r.competenceDays[c.id] || []).includes(group.weekdays[0])
                  ).length;
                  const ok = assigned >= required;
                  return (
                    <th
                      key={c.id}
                      className="cmatrix-required-cell"
                      title={t('competences.staffing_status', { assigned, required })}
                    >
                      <div className={`cmatrix-required-fill ${ok ? 'is-ok' : 'is-off'}`}>
                        <button
                          type="button"
                          className="cmatrix-required-step cmatrix-required-step-minus"
                          onClick={(e) => { e.stopPropagation(); stepRequired(group, c, -1); }}
                          disabled={required <= 0}
                          aria-label={t('competences.decrease_required')}
                          title={t('competences.decrease_required')}
                        >
                          −
                        </button>
                        <span className="cmatrix-required-number">{required}</span>
                        <button
                          type="button"
                          className="cmatrix-required-step cmatrix-required-step-plus"
                          onClick={(e) => { e.stopPropagation(); stepRequired(group, c, 1); }}
                          aria-label={t('competences.increase_required')}
                          title={t('competences.increase_required')}
                        >
                          +
                        </button>
                      </div>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td className="cmatrix-empty-row" colSpan={competenceColSpan + 1}>
                  {columns.length === 0 ? t('competences.empty') : t('departments.no_employees')}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.user_id}>
                  <th className="cmatrix-row">
                    <div className="cmatrix-row-inner">
                      <span className="cmatrix-row-name">{r.full_name || r.email}</span>
                      <button
                        type="button"
                        className={`cmatrix-remove-btn ${removingRowId === r.user_id ? 'is-active' : ''}`}
                        onClick={(e) => {
                          popoverAnchorRef.current = e.currentTarget;
                          setRemovingRowId(r.user_id);
                        }}
                        title={t('departments.remove')}
                        aria-label={t('departments.remove')}
                      >
                        ✕
                      </button>
                    </div>
                  </th>
                  {columns.map((c) => {
                    const assigned = (r.competenceDays[c.id] || []).length > 0;
                    return (
                      <td key={c.id} className="cmatrix-cell-td">
                        <button
                          type="button"
                          className={`cmatrix-daycell ${assigned ? 'is-on' : ''}`}
                          onClick={() => onToggleWeek(r.user_id, c.id)}
                          aria-pressed={assigned}
                          title={c.name}
                          aria-label={t('competences.toggle_week_named', {
                            name: r.full_name || r.email,
                            competence: c.name,
                          })}
                        >
                          <span className="cmatrix-daycell-mark" aria-hidden="true">
                            {assigned ? '✕' : ''}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {splittingGroup &&
        createPortal(
          <div
            className="cmatrix-modal-backdrop"
            role="presentation"
            onMouseDown={(event) => {
              if (event.target === event.currentTarget) setSplittingGroupId(null);
            }}
          >
            <div className="cmatrix-days-modal" role="dialog" aria-modal="true">
              <h3>{t('competences.split_days_title')}</h3>
              <p>{t('competences.split_days_hint')}</p>
              <div className="cmatrix-days-picker">
                {splittingGroup.weekdays.map((weekday) => {
                  const selected = selectedSplitDays.includes(weekday);
                  return (
                    <button
                      type="button"
                      key={weekday}
                      className={`cmatrix-day-option ${selected ? 'is-selected' : ''}`}
                      aria-pressed={selected}
                      onClick={() => toggleSplitDay(weekday)}
                    >
                      {t(`workload.days.${weekday}`)}
                    </button>
                  );
                })}
              </div>
              <div className="cmatrix-popover-actions">
                <button
                  type="button"
                  className="departments-btn"
                  onClick={() => setSplittingGroupId(null)}
                >
                  {t('departments.cancel')}
                </button>
                <button
                  type="button"
                  className="departments-btn departments-btn-primary"
                  disabled={!canConfirmSplit}
                  onClick={confirmSplitDays}
                >
                  {t('competences.create_day_group')}
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}

      {searchOpen &&
        searchResults.length > 0 &&
        suggestRect &&
        createPortal(
          <ul
            ref={suggestElRef}
            className="cmatrix-suggestions"
            style={{ top: suggestRect.bottom, left: suggestRect.left, minWidth: suggestRect.width }}
          >
            {searchResults.map((u) => (
              <li key={u.id}>
                <button type="button" onClick={() => handlePick(u)}>
                  {u.full_name || u.email} ({u.email})
                </button>
              </li>
            ))}
          </ul>,
          document.body
        )}

      {deletingId &&
        deleteRect &&
        (() => {
          const col = columns.find((c) => c.id === deletingId);
          if (!col) return null;
          return createPortal(
            <div
              ref={deleteElRef}
              className="cmatrix-popover"
              role="dialog"
              aria-modal="true"
              style={{
                top: deleteRect.bottom + 6,
                left: Math.max(8, Math.min(deleteRect.left, window.innerWidth - 296)),
              }}
            >
              <p className="cmatrix-popover-text">
                {t('competences.confirm_delete_named', { name: col.name })}
              </p>
              <div className="cmatrix-popover-actions">
                <button
                  type="button"
                  className="departments-btn"
                  onClick={() => setDeletingId(null)}
                >
                  {t('departments.cancel')}
                </button>
                <button
                  type="button"
                  className="departments-btn departments-btn-danger"
                  onClick={() => handleDeleteCompetence(deletingId)}
                >
                  {t('competences.delete')}
                </button>
              </div>
            </div>,
            document.body
          );
        })()}

      {removingRow &&
        popoverRect &&
        createPortal(
          <div
            ref={popoverElRef}
            className="cmatrix-popover"
            role="dialog"
            aria-modal="true"
            style={{ top: popoverRect.bottom + 6, left: popoverRect.left }}
          >
            <p className="cmatrix-popover-text">
              {t('departments.confirm_remove_named', {
                name: removingRow.full_name || removingRow.email,
              })}
            </p>
            <div className="cmatrix-popover-actions">
              <button type="button" className="departments-btn" onClick={() => setRemovingRowId(null)}>
                {t('departments.cancel')}
              </button>
              <button
                type="button"
                className="departments-btn departments-btn-danger"
                onClick={() => handleRemoveRow(removingRow.user_id)}
              >
                {t('departments.remove')}
              </button>
            </div>
          </div>,
          document.body
        )}
    </section>
  );
};

export default CompetenceMatrix;