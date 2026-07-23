import { useState, useMemo, useRef, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
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
 * Props:
 * - columns: [{ id, name, description }] — competences of the ambulance
 * - rows: [{ user_id, email, full_name, competenceIds: number[] }] — draft state
 * - allUsers: [{ id, email, full_name }] — hospital-wide pool for the search box
 * - loading: table is (re)loading
 * - onToggleCell(userId, competenceId)
 * - onAddRow(user)
 * - onRemoveRow(userId)
 * - onAddCompetence(name): Promise
 * - onUpdateRequiredCount(competenceId, requiredCount): Promise
 * - onDeleteCompetence(competenceId): Promise
 */
const CompetenceMatrix = ({
  columns,
  rows,
  allUsers,
  loading,
  onToggleCell,
  onAddRow,
  onRemoveRow,
  onAddCompetence,
  onUpdateRequiredCount,
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
  const requiredOf = (col) => col.required_count ?? col.count ?? 1;

  const [editingRequiredId, setEditingRequiredId] = useState(null);

  const stepRequired = (col, delta) => {
    const next = Math.max(1, requiredOf(col) + delta);
    onUpdateRequiredCount(col.id, next);
  };

  const closeRequiredEdit = () => setEditingRequiredId(null);

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
            {columns.length > 0 && (
              <tr className="cmatrix-required-row">
                <th className="cmatrix-corner cmatrix-required-label">
                  Potrebný počet zamestnancov
                </th>
                {columns.map((c) => {
                  const required = requiredOf(c);
                  const assigned = rows.filter((r) => r.competenceIds.includes(c.id)).length;
                  const ok = assigned === required;
                  const isEditing = editingRequiredId === c.id;
                  return (
                    <th
                      key={c.id}
                      className={`cmatrix-required-cell ${ok ? 'is-ok' : 'is-off'} ${isEditing ? 'is-editing' : ''}`}
                      title={isEditing ? undefined : `Označení: ${assigned} / potrební: ${required}`}
                    >
                      {isEditing ? (
                        /* Stepper shown after pencil click */
                        <span className="cmatrix-required-stepper">
                          <button
                            type="button"
                            className="cmatrix-required-arrow"
                            onClick={(e) => { e.stopPropagation(); stepRequired(c, -1); }}
                            disabled={required <= 1}
                            aria-label="Znížiť počet"
                          >
                            ▼
                          </button>
                          <span className="cmatrix-required-number">{required}</span>
                          <button
                            type="button"
                            className="cmatrix-required-arrow"
                            onClick={(e) => { e.stopPropagation(); stepRequired(c, 1); }}
                            aria-label="Zvýšiť počet"
                          >
                            ▲
                          </button>
                          <button
                            type="button"
                            className="cmatrix-required-close"
                            onClick={(e) => { e.stopPropagation(); closeRequiredEdit(); }}
                            aria-label="Zatvoriť"
                          >
                            ✕
                          </button>
                        </span>
                      ) : (
                        /* Normal view: pencil appears on cell hover (left edge) */
                        <span className="cmatrix-required-view">
                          <button
                            type="button"
                            className="cmatrix-required-pencil"
                            onClick={(e) => { e.stopPropagation(); setEditingRequiredId(c.id); }}
                            aria-label="Upraviť potrebný počet"
                            title="Upraviť potrebný počet"
                          >
                            ✎
                          </button>
                          <span className="cmatrix-required-number">{required}</span>
                        </span>
                      )}
                    </th>
                  );
                })}
              </tr>
            )}
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
                    const has = r.competenceIds.includes(c.id);
                    return (
                      <td key={c.id} className="cmatrix-cell-td">
                        <button
                          type="button"
                          className={`cmatrix-cell ${has ? 'is-on' : ''}`}
                          onClick={() => onToggleCell(r.user_id, c.id)}
                          aria-pressed={has}
                          aria-label={`${r.full_name || r.email} — ${c.name}`}
                        >
                          {has ? '✕' : ''}
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