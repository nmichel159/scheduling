import { useState, useMemo, useRef, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { ISO_WEEKDAYS, requiredCountForGroup } from '../utils/competenceRequirements';
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
 * The "Potrebný počet" header rows are READ-ONLY here: they spell out,
 * per day-group (e.g. Po–Pi vs So–Ne), how many people with that
 * competence the ambulance needs on those days. Changing those numbers
 * (and regrouping days) belongs to the competence-scenario screen — this
 * screen is only about who can do what, and the compact table above the
 * grid is there for orientation, not for editing. Each group still
 * carries a full seven-slot week track and fills in only the days it
 * owns, so Monday sits at the same x in every row and a group reads as
 * one connected pill.
 *
 * Props:
 * - columns: [{ id, name, description }] — competences of the ambulance
 * - dayGroups: [{ id, weekdays }] — groups the required counts are shown for
 * - rows: [{ user_id, email, full_name, competenceDays: { [competenceId]: number[] } }] — draft state.
 *   competenceDays[competenceId] holds the ISO weekdays (0=Po..6=Ne) on which
 *   that employee holds that competence; a missing/empty entry means "not assigned".
 *   This view only ever sets it to "all 7 days" or empty (see onToggleWeek).
 * - allUsers: [{ id, email, full_name }] — hospital-wide pool for the add box
 * - loading: table is (re)loading
 * - onToggleWeek(userId, competenceId) — assign/clear the competence for the whole week
 * - onAddRow(user)
 * - onRemoveRow(userId)
 *
 * The competence list itself (adding/removing a competence of the
 * ambulance) is NOT editable here — it belongs to the competence-scenario
 * screen. This table only says who can do which of them.
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
}) => {
  const { t } = useTranslation();

  const [filter, setFilter] = useState('');
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState('');
  const [removingRowId, setRemovingRowId] = useState(null);
  const [detailRowId, setDetailRowId] = useState(null);

  /* ---------- required head-count rows (read-only) ---------- */

  const requiredOf = (col, group) => requiredCountForGroup(col, group);

  /* ---------- table filter ----------
   * Purely visual: hides rows that don't match, without touching the
   * draft. Cells of hidden rows keep whatever the user set on them.
   */
  const visibleRows = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        (r.full_name || '').toLowerCase().includes(q) ||
        r.email.toLowerCase().includes(q)
    );
  }, [rows, filter]);

  /* ---------- employee picker (add row) ----------
   * Opened from the explicit "+ Pridať zamestnanca" button, so that
   * adding a person and filtering the table are two visibly separate
   * controls. The dropdown opens with the full list of assignable users
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

  const closeAdd = () => {
    setAdding(false);
    setSearch('');
  };

  const handlePick = (user) => {
    onAddRow(user);
    setSearch('');
  };

  /* ---------- floating layers (dropdown + popovers) ----------
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
    if (!adding || !searchAnchorRef.current) return;
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
        closeAdd();
      }
    };
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') closeAdd();
    };
    document.addEventListener('mousedown', handleMouseDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      window.removeEventListener('scroll', update, true);
      window.removeEventListener('resize', update);
      document.removeEventListener('mousedown', handleMouseDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [adding]);

  const popoverAnchorRef = useRef(null);
  const popoverElRef = useRef(null);
  const [popoverRect, setPopoverRect] = useState(null);
  const [popoverHeight, setPopoverHeight] = useState(0);

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

  /* The confirm popover normally hangs below the ✕ it belongs to, but the
   * last rows of a long table sit at the bottom of the viewport, where
   * that would push "Odobrať" off screen. Measure the rendered popover and
   * flip it above the anchor when it doesn't fit below. */
  useLayoutEffect(() => {
    if (!removingRowId || !popoverElRef.current) return;
    setPopoverHeight(popoverElRef.current.offsetHeight);
  }, [removingRowId, popoverRect]);

  /* Employee detail modal — read-only for now; this is the place where
   * editing the person (name, e-mail, …) will live later. */
  useLayoutEffect(() => {
    if (!detailRowId) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setDetailRowId(null);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [detailRowId]);

  /* ---------- row removal (confirm) ---------- */

  const handleRemoveRow = (userId) => {
    onRemoveRow(userId);
    setRemovingRowId(null);
  };

  /* ---------- render ---------- */

  const competenceColSpan = Math.max(columns.length, 1);
  const removingRow = rows.find((r) => r.user_id === removingRowId) || null;
  const detailRow = rows.find((r) => r.user_id === detailRowId) || null;

  /* The backend keeps a single `full_name`; the dialog shows it split into
   * given/family name the way a future edit form will collect it. */
  const splitName = (fullName) => {
    const parts = (fullName || '').trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return { first: '', last: '' };
    return { first: parts[0], last: parts.slice(1).join(' ') };
  };
  const detailName = detailRow ? splitName(detailRow.full_name) : null;

  /* Below the anchor when it fits, above it when it doesn't, always inside
   * the viewport. `height` is 0 on the very first paint (nothing measured
   * yet); the effect above fills it in and re-renders. */
  const placePopover = (rect, height) => {
    const below = rect.bottom + 6;
    const fitsBelow = !height || below + height <= window.innerHeight - 8;
    return {
      top: fitsBelow ? below : Math.max(8, rect.top - 6 - height),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 276)),
    };
  };

  return (
    <section className="cmatrix">
      <div className={`cmatrix-scroll ${loading ? 'is-loading' : ''}`}>
        <table className="cmatrix-table">
          <thead>
            <tr className="cmatrix-group-row">
              <th className="cmatrix-corner">{t('competences.employee')}</th>
              <th className="cmatrix-group-header" colSpan={competenceColSpan}>
                <span className="cmatrix-group-title">{t('competences.title')}</span>
              </th>
            </tr>
            <tr>
              <th className="cmatrix-corner cmatrix-tools-th">
                {/* Filter (left) and add (right) are deliberately two separate
                  * controls: one narrows the table, the other puts a new
                  * person into it. */}
                <div className="cmatrix-tools">
                  <div className={`cmatrix-filter ${filter ? 'is-active' : ''}`}>
                    <span className="cmatrix-filter-icon" aria-hidden="true">⌕</span>
                    <input
                      type="text"
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                      placeholder={t('competences.filter_placeholder')}
                      aria-label={t('competences.filter_placeholder')}
                    />
                    {filter && (
                      <button
                        type="button"
                        className="cmatrix-filter-clear"
                        onClick={() => setFilter('')}
                        title={t('competences.clear_filter')}
                        aria-label={t('competences.clear_filter')}
                      >
                        ✕
                      </button>
                    )}
                  </div>

                  <div className="cmatrix-addrow" ref={searchAnchorRef}>
                    {adding ? (
                      <input
                        type="text"
                        autoFocus
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder={t('competences.search_placeholder')}
                        aria-label={t('competences.search_placeholder')}
                      />
                    ) : (
                      <button
                        type="button"
                        className="cmatrix-addbtn cmatrix-addbtn-wide"
                        onClick={() => setAdding(true)}
                        title={t('competences.add_employee')}
                      >
                        <span className="cmatrix-addbtn-plus" aria-hidden="true">+</span>
                        {t('competences.add_employee')}
                      </button>
                    )}
                  </div>
                </div>
              </th>
              {columns.map((c) => (
                <th key={c.id} className="cmatrix-col" title={c.description || c.name}>
                  <span className="cmatrix-colname">{c.name}</span>
                </th>
              ))}
            </tr>
            {columns.length > 0 && dayGroups.map((group, index) => {
              const groupDays = new Set(group.weekdays);
              return (
                <tr
                  className={`cmatrix-required-row ${index % 2 === 1 ? 'is-alt' : ''}`}
                  key={group.id}
                >
                  <th className="cmatrix-corner cmatrix-required-label">
                    {/* Full week track: every row lays out all seven slots and
                      * fills only the days it owns, so Monday keeps the same x
                      * in every row and the days of one group join into a
                      * single pill via the is-start/is-end rounding. */}
                    <div className="cmatrix-day-track">
                      {ISO_WEEKDAYS.map((weekday) => {
                        if (!groupDays.has(weekday)) {
                          return (
                            <span
                              key={weekday}
                              className="cmatrix-day-empty"
                              aria-hidden="true"
                            />
                          );
                        }
                        const className = [
                          'cmatrix-day',
                          groupDays.has(weekday - 1) ? '' : 'is-start',
                          groupDays.has(weekday + 1) ? '' : 'is-end',
                        ]
                          .filter(Boolean)
                          .join(' ');
                        return (
                          <span key={weekday} className={className}>
                            {t(`workload.days.${weekday}`)}
                          </span>
                        );
                      })}
                    </div>
                  </th>
                  {columns.map((c) => (
                    <th key={c.id} className="cmatrix-required-cell">
                      <div
                        className="cmatrix-required-fill"
                        title={t('competences.required_count')}
                      >
                        <span className="cmatrix-required-number">
                          {requiredOf(c, group)}
                        </span>
                      </div>
                    </th>
                  ))}
                </tr>
              );
            })}
          </thead>
          <tbody>
            {visibleRows.length === 0 ? (
              <tr>
                <td className="cmatrix-empty-row" colSpan={competenceColSpan + 1}>
                  {rows.length > 0
                    ? t('competences.no_filter_match')
                    : columns.length === 0
                      ? t('competences.empty')
                      : t('departments.no_employees')}
                </td>
              </tr>
            ) : (
              visibleRows.map((r) => (
                <tr key={r.user_id}>
                  <th className="cmatrix-row">
                    <div className="cmatrix-row-inner">
                      <button
                        type="button"
                        className="cmatrix-row-name"
                        onClick={() => setDetailRowId(r.user_id)}
                        title={t('competences.employee_detail')}
                      >
                        <span className="cmatrix-row-name-text">
                          {r.full_name || r.email}
                        </span>
                      </button>
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

      {adding &&
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

      {removingRow &&
        popoverRect &&
        createPortal(
          <div
            ref={popoverElRef}
            className="cmatrix-popover"
            role="dialog"
            aria-modal="true"
            style={placePopover(popoverRect, popoverHeight)}
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

      {detailRow &&
        createPortal(
          <div
            className="cmatrix-modal-backdrop"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setDetailRowId(null);
            }}
          >
            <div className="cmatrix-modal" role="dialog" aria-modal="true">
              <header className="cmatrix-modal-head">
                <div className="cmatrix-modal-avatar" aria-hidden="true">
                  {(detailRow.full_name || detailRow.email).trim().charAt(0).toUpperCase()}
                </div>
                <div className="cmatrix-modal-heading">
                  <h3 className="cmatrix-modal-title">
                    {detailRow.full_name || detailRow.email}
                  </h3>
                  <p className="cmatrix-modal-subtitle">
                    {t('competences.employee_detail')}
                  </p>
                </div>
                <button
                  type="button"
                  className="cmatrix-modal-close"
                  onClick={() => setDetailRowId(null)}
                  title={t('departments.cancel')}
                  aria-label={t('departments.cancel')}
                >
                  ✕
                </button>
              </header>

              <dl className="cmatrix-modal-fields">
                <div>
                  <dt>{t('competences.first_name')}</dt>
                  <dd>{detailName.first || '—'}</dd>
                </div>
                <div>
                  <dt>{t('competences.last_name')}</dt>
                  <dd>{detailName.last || '—'}</dd>
                </div>
                <div>
                  <dt>{t('competences.email')}</dt>
                  <dd>{detailRow.email}</dd>
                </div>
                <div>
                  <dt>{t('competences.title')}</dt>
                  <dd>
                    {columns
                      .filter((c) => (detailRow.competenceDays[c.id] || []).length > 0)
                      .map((c) => c.name)
                      .join(', ') || '—'}
                  </dd>
                </div>
              </dl>

              <p className="cmatrix-modal-note">{t('competences.detail_readonly')}</p>

              <div className="cmatrix-popover-actions">
                <button
                  type="button"
                  className="departments-btn"
                  onClick={() => setDetailRowId(null)}
                >
                  {t('competences.close_detail')}
                </button>
              </div>
            </div>
          </div>,
          document.body
        )}
    </section>
  );
};

export default CompetenceMatrix;
