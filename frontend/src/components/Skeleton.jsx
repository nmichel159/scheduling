/**
 * Placeholder shapes for a screen whose first answer is still on its way.
 * The page keeps its title and its outline instead of collapsing to a
 * spinner and a sentence, so nothing jumps when the data lands.
 *
 * `label` is what a screen reader hears ("Načítavam..."); none of it is drawn.
 * The shapes themselves are styled in styles/ui.css.
 */

/** Widths the placeholder lines cycle through, so the rows do not look ruled. */
const LINE_WIDTHS = [46, 34, 52, 30, 42, 38];

/** A list or a table: a round mark, a line of text, a figure at the end. */
export const SkeletonRows = ({ rows = 6, label }) => (
  <div className="skeleton-rows" role="status" aria-busy="true">
    {label && <span className="visually-hidden">{label}</span>}
    {Array.from({ length: rows }, (_, index) => (
      <div className="skeleton-row" key={index} aria-hidden="true">
        <span className="skeleton skeleton-dot" />
        <span
          className="skeleton skeleton-line"
          style={{ width: `${LINE_WIDTHS[index % LINE_WIDTHS.length]}%` }}
        />
        <span className="skeleton skeleton-line is-end" />
      </div>
    ))}
  </div>
);

/** A calendar or a matrix: `columns` across, `cells` in all. */
export const SkeletonGrid = ({ cells = 35, columns = 7, label }) => (
  <div
    className="skeleton-grid"
    style={{ '--skeleton-columns': columns }}
    role="status"
    aria-busy="true"
  >
    {label && <span className="visually-hidden">{label}</span>}
    {Array.from({ length: cells }, (_, index) => (
      <span className="skeleton skeleton-cell" key={index} aria-hidden="true" />
    ))}
  </div>
);

/**
 * A whole screen in waiting: its real title over one card of placeholders.
 *
 * Props:
 * - className: the classes of the screen's own root, so the placeholder sits
 *   in the same column the screen will
 * - title: the screen's title, already known while its data is not
 * - variant: 'rows' (default) or 'grid'
 * - rows: how many rows the 'rows' variant draws
 * - label: see above
 */
const PageSkeleton = ({ className = 'page', title, variant = 'rows', rows, label }) => (
  <div className={className}>
    <header className="page-header">
      <h1 className="page-title">{title}</h1>
    </header>
    <div className="card">
      {variant === 'grid' ? (
        <SkeletonGrid label={label} />
      ) : (
        <SkeletonRows rows={rows} label={label} />
      )}
    </div>
  </div>
);

export default PageSkeleton;
