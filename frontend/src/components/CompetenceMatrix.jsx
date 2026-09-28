import { useState, useMemo, useRef, useLayoutEffect, useId } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { CheckIcon, CloseIcon, PlusIcon } from './NavIcons';
import {
  REQUIREMENT_SLOTS,
  SPECIAL_DAY_SLOT,
  requiredCountForGroup,
} from '../utils/competenceRequirements';
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
 * `onToggleWeek` flips). The whole cell area is clickable (not just the
 * small checkbox drawn in its middle) — see .cmatrix-toggle in the CSS.
 *
 * The filter and the "add employee" picker sit in a toolbar above the
 * table; the table scrolls inside its own box, so its head and the name
 * column stay in view however far a long roster or a wide codebook is
 * scrolled.
 *
 * The "Potrebný počet" header rows are READ-ONLY here: they spell out,
 * per day-group (e.g. Po–Pi vs So–Ne), how many people with that
 * competence the ambulance needs on those days. The eighth slot of each
 * row is the day of rest — what a public holiday wants, whatever weekday
 * it lands on. A row exists per distinct set of numbers, so the day of
 * rest shares the week's row until it asks for something else. Changing
 * those numbers (and regrouping days) belongs to the competence-scenario
 * screen — this screen is only about who can do what, and the compact
 * table above the grid is there for orientation, not for editing. See
 * `renderRequiredRow` for how a row is laid out.
 *
 * Props:
 * - columns: [{ id, name, description }] — competences of the ambulance
 * - dayGroups: [{ id, weekdays }] — slot groups the required counts are shown
 *   for; `weekdays` may include SPECIAL_DAY_SLOT alongside real weekdays
 * - rows: [{ user_id, email, full_name, competenceDays: { [competenceId]: number[] } }] — draft state.
 *   competenceDays[competenceId] holds the ISO weekdays (0=Po..6=Ne) on which
 *   that employee holds that competence; a missing/empty entry means "not assigned".
 *   This view only ever sets it to "all 7 days" or empty (see onToggleWeek).
 * - allUsers: [{ id, email, full_name }] — hospital-wide pool for the add box
 * - loading: table is (re)loading
 * - onToggleWeek(userId, competenceId) — assign/clear the competence for the whole week
 * - onAddRow(user)
 * - onRemoveRow(userId)
 * - onOpenProfile(userId) — the name is a link to the person's profile; the
 *   parent owns the dialog, because opening it reads the workplace's own
 *   record of that person and saving it writes the table
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
  onOpenProfile,
}) => {
  const { t } = useTranslation();

  const [filter, setFilter] = useState('');
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const [removingRowId, setRemovingRowId] = useState(null);
  const listboxId = useId();

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
    setActiveIndex(0);
  };

  const handlePick = (user) => {
    onAddRow(user);
    setSearch('');
    setActiveIndex(0);
  };

  /* The list is portaled to <body>, so Tab from the field would never reach
   * it. The arrows walk the list instead and Enter adds the highlighted
   * person, the way a combobox behaves. */
  const handleSearchKeyDown = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (searchResults.length === 0) return;
      const step = e.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex(
        (prev) => (prev + step + searchResults.length) % searchResults.length
      );
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const user = searchResults[Math.min(activeIndex, searchResults.length - 1)];
      if (user) handlePick(user);
    }
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
      if (e.key === 'Escape') {
        setRemovingRowId(null);
        if (document.body.contains(anchor)) anchor.focus();
      }
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

  /* The popover lives at the end of <body>, far from the ✕ in tab order, so
   * it takes the focus when it opens — otherwise a keyboard user would open
   * it and be unable to reach its buttons. */
  useLayoutEffect(() => {
    if (!removingRowId || !popoverRect || !popoverElRef.current) return;
    if (popoverElRef.current.contains(document.activeElement)) return;
    popoverElRef.current.querySelector('button')?.focus();
  }, [removingRowId, popoverRect]);

  /* ---------- row removal (confirm) ---------- */

  const closeRemove = () => {
    const anchor = popoverAnchorRef.current;
    setRemovingRowId(null);
    if (anchor && document.body.contains(anchor)) anchor.focus();
  };

  const handleRemoveRow = (userId) => {
    onRemoveRow(userId);
    setRemovingRowId(null);
  };

  /* ---------- render ---------- */

  const competenceColSpan = Math.max(columns.length, 1);
  const removingRow = rows.find((r) => r.user_id === removingRowId) || null;

  /* Below the anchor when it fits, above it when it doesn't, always inside
   * the viewport. `height` is 0 on the very first paint (nothing measured
   * yet); the effect above fills it in and re-renders. */
  const placePopover = (rect, height) => {
    const below = rect.bottom + 6;
    const fitsBelow = !height || below + height <= window.innerHeight - 8;
    return {
      top: fitsBelow ? below : Math.max(8, rect.top - 6 - height),
      left: Math.max(8, Math.min(rect.left, window.innerWidth - 288)),
    };
  };

  /* The picker's list hangs under the field, right edges aligned — the add
   * control sits at the right end of the toolbar, so a list growing to the
   * right would leave the window. */
  const placeSuggestions = (rect) => ({
    top: rect.bottom + 4,
    right: Math.max(8, window.innerWidth - rect.right),
    minWidth: rect.width,
  });

  const activeOption = adding && searchResults.length > 0
    ? Math.min(activeIndex, searchResults.length - 1)
    : -1;

  /* One row of the requirement block: the slots that want the same numbers,
   * then those numbers, one per competence.
   *
   * Every row lays out all eight slots and fills in only the ones it owns,
   * the rest staying as faint dots: Monday therefore keeps the same x down
   * the whole block (the week reads vertically too), and the days of one
   * group join into a single pill through the is-start/is-end rounding
   * instead of scattering into separate chips.
   *
   * The eighth slot is the day of rest, and it shares a row with the week
   * whenever it wants the same numbers — a row is a statement about counts,
   * so one split off to repeat them would say nothing. What keeps it from
   * passing for a weekday is the layout: it stands behind a fence, carries
   * its own mark, and keeps both rounded ends however the days beside it
   * are grouped. That is also why the run is measured over the weekdays
   * alone — Sunday has to close the pill even when the day of rest sits on
   * the same row.
   */
  const renderRequiredRow = (group, index) => {
    const groupSlots = new Set(group.weekdays);
    const inWeekRun = (slot) =>
      slot >= 0 && slot < SPECIAL_DAY_SLOT && groupSlots.has(slot);
    return (
      <tr key={group.id} className="cmatrix-required-row">
        <th className="cmatrix-first cmatrix-required-label">
          {index === 0 && (
            <span className="cmatrix-required-caption">
              {t('competences.required_count')}
            </span>
          )}
          <div className="cmatrix-day-track">
            {REQUIREMENT_SLOTS.map((slot) => {
              const special = slot === SPECIAL_DAY_SLOT;
              if (!groupSlots.has(slot)) {
                return (
                  <span
                    key={slot}
                    className={`cmatrix-day-empty ${special ? 'is-special' : ''}`.trim()}
                    aria-hidden="true"
                  />
                );
              }
              return (
                <span
                  key={slot}
                  className={[
                    'cmatrix-day',
                    special ? 'is-special' : '',
                    special || !inWeekRun(slot - 1) ? 'is-start' : '',
                    special || !inWeekRun(slot + 1) ? 'is-end' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  title={special ? t('special_days.column_hint') : undefined}
                >
                  {special
                    ? t('special_days.column_short')
                    : t(`workload.days.${slot}`)}
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
  };

  return (
    <section className="cmatrix card">
      {/* Filter (left) and add (right) are deliberately two separate
        * controls: one narrows the table, the other puts a new person
        * into it. */}
      <div className="cmatrix-toolbar">
        <div className="cmatrix-filter">
          <input
            type="text"
            className="input search-input"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && filter) setFilter('');
            }}
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
              <CloseIcon className="icon-sm" />
            </button>
          )}
        </div>

        <span className="cmatrix-count">
          {filter
            ? `${visibleRows.length} / ${rows.length}`
            : t('departments.employee_count', { count: rows.length })}
        </span>

        <div className="cmatrix-addrow" ref={searchAnchorRef}>
          {adding ? (
            <input
              type="text"
              className="input search-input"
              autoFocus
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder={t('competences.search_placeholder')}
              aria-label={t('competences.search_placeholder')}
              role="combobox"
              aria-expanded={searchResults.length > 0}
              aria-controls={listboxId}
              aria-autocomplete="list"
              aria-activedescendant={
                activeOption >= 0 ? `${listboxId}-${activeOption}` : undefined
              }
            />
          ) : (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setAdding(true)}
            >
              <PlusIcon />
              {t('competences.add_employee')}
            </button>
          )}
        </div>
      </div>

      <div className={`cmatrix-scroll ${loading ? 'is-loading' : ''}`.trim()}>
        <table className="cmatrix-table">
          <thead>
            <tr className="cmatrix-names-row">
              <th className="cmatrix-first cmatrix-corner" scope="col">
                {t('competences.employee')}
              </th>
              {columns.map((c) => (
                <th
                  key={c.id}
                  className="cmatrix-col"
                  scope="col"
                  title={c.description || c.name}
                >
                  <span className="cmatrix-colname">{c.name}</span>
                </th>
              ))}
            </tr>
            {columns.length > 0 &&
              dayGroups.map((group, index) => renderRequiredRow(group, index))}
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
                  <th className="cmatrix-first cmatrix-row" scope="row">
                    <div className="cmatrix-row-inner">
                      <button
                        type="button"
                        className="cmatrix-row-name"
                        onClick={() => onOpenProfile(r.user_id)}
                        title={`${t('competences.employee_detail')} — ${r.email}`}
                      >
                        <span className="cmatrix-row-name-text">
                          {r.full_name || r.email}
                        </span>
                      </button>
                      <button
                        type="button"
                        className={`cmatrix-remove-btn ${removingRowId === r.user_id ? 'is-active' : ''}`.trim()}
                        onClick={(e) => {
                          popoverAnchorRef.current = e.currentTarget;
                          setRemovingRowId(r.user_id);
                        }}
                        title={t('departments.remove')}
                        aria-label={`${t('departments.remove')} — ${r.full_name || r.email}`}
                      >
                        <CloseIcon />
                      </button>
                    </div>
                  </th>
                  {columns.map((c) => {
                    const assigned = (r.competenceDays[c.id] || []).length > 0;
                    return (
                      <td key={c.id} className="cmatrix-cell-td">
                        <button
                          type="button"
                          className={`cmatrix-toggle ${assigned ? 'is-on' : ''}`.trim()}
                          onClick={() => onToggleWeek(r.user_id, c.id)}
                          aria-pressed={assigned}
                          title={c.name}
                          aria-label={t('competences.toggle_week_named', {
                            name: r.full_name || r.email,
                            competence: c.name,
                          })}
                        >
                          <span className="cmatrix-check" aria-hidden="true">
                            {assigned && <CheckIcon />}
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
        suggestRect &&
        createPortal(
          <ul
            ref={suggestElRef}
            id={listboxId}
            role="listbox"
            className="cmatrix-suggestions"
            style={placeSuggestions(suggestRect)}
          >
            {searchResults.length === 0 ? (
              <li className="cmatrix-suggestions-empty" role="presentation">
                {t('competences.no_filter_match')}
              </li>
            ) : (
              searchResults.map((u, index) => (
                <li
                  key={u.id}
                  id={`${listboxId}-${index}`}
                  role="option"
                  aria-selected={index === activeOption}
                >
                  <button
                    type="button"
                    tabIndex={-1}
                    // Keeps the focus in the field, so the next name can be
                    // typed straight after a click.
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => handlePick(u)}
                  >
                    <span className="cmatrix-suggestion-name">
                      {u.full_name || u.email}
                    </span>
                    {u.full_name && (
                      <span className="cmatrix-suggestion-email">{u.email}</span>
                    )}
                  </button>
                </li>
              ))
            )}
          </ul>,
          document.body
        )}

      {removingRow &&
        popoverRect &&
        createPortal(
          <div
            ref={popoverElRef}
            className="cmatrix-popover"
            role="alertdialog"
            aria-label={t('departments.remove')}
            style={placePopover(popoverRect, popoverHeight)}
          >
            <p className="cmatrix-popover-text">
              {t('departments.confirm_remove_named', {
                name: removingRow.full_name || removingRow.email,
              })}
            </p>
            <div className="cmatrix-popover-actions">
              <button type="button" className="btn btn-sm" onClick={closeRemove}>
                {t('departments.cancel')}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
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
