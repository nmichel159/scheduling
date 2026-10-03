import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ConflictIcon from './ConflictIcon';

/** What each mark in the month-by-person grid stands for. */
const GRID_MARKS = [
  ['duty', 'is-duty'],
  ['elsewhere', 'is-elsewhere'],
  ['cannot', 'is-cannot'],
  ['wanted', 'is-wanted'],
  ['rather_not', 'is-rather-not'],
  ['conflict', 'is-conflict'],
  ['warning', 'is-warning'],
  ['weekend', 'is-weekend'],
  ['today', 'is-today'],
];

/** The glyphs the duty pickers show beside a name, in the order of weight. */
const PICKER_GLYPHS = [
  'unavailable',
  'unqualified',
  'double_role',
  'other_workplace',
  'rest',
  'over_wish',
  'soft_decline',
];

/**
 * A small "Legend" button that opens the key to the marks beside it. The key
 * opens in place rather than floating, so no popover edge can clip it.
 *
 * `kind` picks the key: 'grid' for the month-by-person marks, 'picker' for
 * the glyphs next to a name in the duty picker.
 */
const PlannerLegend = ({ kind = 'grid' }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className={`marks-key is-${kind} ${open ? 'is-open' : ''}`}>
      <button
        type="button"
        className="marks-key-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && open) {
            e.stopPropagation();
            setOpen(false);
          }
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="8.4" />
          <path d="M12 11v5.2M12 7.8h.01" />
        </svg>
        {t('schedule_edit.marks_legend.button')}
      </button>
      {open && (
        <ul id={panelId} className="marks-key-panel">
          {kind === 'picker'
            ? PICKER_GLYPHS.map((type) => (
                <li key={type} className="marks-key-item">
                  <ConflictIcon type={type} className="planner-conflict-glyph" />
                  {t(`schedule_edit.marks_legend.picker.${type}`)}
                </li>
              ))
            : GRID_MARKS.map(([key, variant]) => (
                <li key={key} className="marks-key-item">
                  <span className={`marks-key-mark ${variant}`} aria-hidden="true" />
                  {t(`schedule_edit.marks_legend.grid.${key}`)}
                </li>
              ))}
        </ul>
      )}
    </div>
  );
};

export default PlannerLegend;
