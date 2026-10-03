import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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

const EDGE = 8;
const GAP = 8;

/**
 * A small "Legend" button; its key opens as a bubble beside it.
 *
 * The bubble is portalled to <body> and pinned to the button: the duty picker
 * it can sit in clips its own overflow, and a bubble inside would be cut off.
 * `kind` picks the key: 'grid' for the month-by-person marks, 'picker' for the
 * glyphs next to a name in the duty picker.
 */
const PlannerLegend = ({ kind = 'grid' }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState(null);
  const buttonRef = useRef(null);
  const bubbleRef = useRef(null);
  const bubbleId = useId();

  // Pin the bubble under the button, right edges aligned, flipped above when
  // there is no room below, and kept inside the window either way.
  useLayoutEffect(() => {
    if (!open || !buttonRef.current || !bubbleRef.current) return;
    const anchor = buttonRef.current.getBoundingClientRect();
    const { offsetWidth: width, offsetHeight: height } = bubbleRef.current;
    const left = Math.min(
      Math.max(EDGE, anchor.right - width),
      window.innerWidth - width - EDGE
    );
    const below = anchor.bottom + GAP;
    const top =
      below + height <= window.innerHeight - EDGE
        ? below
        : Math.max(EDGE, anchor.top - GAP - height);
    setPosition({ left, top });
  }, [open, kind]);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(false);
    // Capture phase, so Escape closes the key first and leaves the picker
    // that holds the button open.
    const handleKeyDown = (e) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      close();
    };
    const handlePointerDown = (e) => {
      if (bubbleRef.current?.contains(e.target) || buttonRef.current?.contains(e.target)) return;
      close();
    };
    const handleScroll = (e) => {
      if (!bubbleRef.current?.contains(e.target)) close();
    };
    window.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('scroll', handleScroll, true);
    window.addEventListener('resize', close);
    return () => {
      window.removeEventListener('keydown', handleKeyDown, true);
      document.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('scroll', handleScroll, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={`marks-key-toggle ${open ? 'is-open' : ''}`}
        aria-expanded={open}
        aria-controls={open ? bubbleId : undefined}
        onClick={() => {
          setPosition(null);
          setOpen((value) => !value);
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="8.4" />
          <path d="M12 11v5.2M12 7.8h.01" />
        </svg>
        {t('schedule_edit.marks_legend.button')}
      </button>
      {open &&
        createPortal(
          <div
            ref={bubbleRef}
            id={bubbleId}
            role="dialog"
            className="marks-key-bubble"
            style={{
              left: position?.left ?? 0,
              top: position?.top ?? 0,
              visibility: position ? 'visible' : 'hidden',
            }}
          >
            <ul className="marks-key-list">
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
          </div>,
          document.body
        )}
    </>
  );
};

export default PlannerLegend;
