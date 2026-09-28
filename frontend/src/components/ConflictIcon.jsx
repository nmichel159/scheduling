/**
 * One glyph per schedule conflict type (utils/scheduleConflicts.js).
 *
 * Drawn on the same 24px grid as the navigation icons and in currentColor, so
 * the severity colour comes from wherever the glyph sits. The stroke is a
 * little heavier than theirs: these are read at 12-14px, next to a name.
 */

const GLYPHS = {
  // The competence badge, struck through.
  unqualified: (
    <>
      <circle cx="12" cy="9" r="5.2" />
      <path d="M8.6 13.4 7.6 20.6l4.4-2.4 4.4 2.4-1-7.2" />
      <path d="M4 4l16 16" />
    </>
  ),
  // No entry.
  unavailable: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="m6.1 6.1 11.8 11.8" />
    </>
  ),
  // Two roles overlapping on one day.
  double_role: (
    <>
      <circle cx="9" cy="12" r="5.6" />
      <circle cx="15" cy="12" r="5.6" />
    </>
  ),
  // Another building.
  other_workplace: (
    <path d="M4.6 20.4V6.6A1.4 1.4 0 0 1 6 5.2h6v15.2M12 20.4V10h6a1.4 1.4 0 0 1 1.4 1.4v9M2.8 20.4h18.4M7.6 9h1.4M7.6 12.6h1.4M7.6 16.2h1.4" />
  ),
  // Sleep: the rest that was not kept.
  rest: <path d="M20.2 14.2A8.2 8.2 0 0 1 9.8 3.8a8.2 8.2 0 1 0 10.4 10.4z" />,
  // A person missing.
  understaffed: (
    <>
      <circle cx="10" cy="8" r="3.6" />
      <path d="M3.4 20.2c.5-3.7 3.1-5.9 6.6-5.9 1.3 0 2.5.3 3.5.9" />
      <path d="M15.6 18h6" />
    </>
  ),
  // A person too many.
  overstaffed: (
    <>
      <circle cx="10" cy="8" r="3.6" />
      <path d="M3.4 20.2c.5-3.7 3.1-5.9 6.6-5.9 1.3 0 2.5.3 3.5.9" />
      <path d="M15.6 18h6M18.6 15v6" />
    </>
  ),
  // Past the line the employee drew.
  over_wish: (
    <>
      <path d="M3.8 10.4h16.4" />
      <path d="M12 20.4V4.2m0 0-4 4m4-4 4 4" />
    </>
  ),
  // Would rather not.
  soft_decline: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M8.4 16.4c1-1.2 2.2-1.9 3.6-1.9s2.6.7 3.6 1.9" />
      <path d="M9 9.6h.01M15 9.6h.01" />
    </>
  ),
};

const ConflictIcon = ({ type, className = 'conflict-icon' }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    {GLYPHS[type] ?? GLYPHS.unavailable}
  </svg>
);

export default ConflictIcon;
