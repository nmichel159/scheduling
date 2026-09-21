/**
 * Shared employee-name formatting for the ambulance schedule views.
 *
 * The chips in the schedule (calendar grid + "daily rows" list) show a
 * short, uniform label — first-name initial + surname, no academic titles —
 * so the chip width stays predictable regardless of how long someone's real
 * name is. The full name is still available via the `title` tooltip on the
 * chip, so nothing is actually lost, just visually compacted.
 */

// Common Slovak/Czech academic and professional titles that may appear
// before or after a person's name. Extend this list if new ones show up.
const LEADING_TITLES = [
  'prof\\.',
  'doc\\.',
  'MUDr\\.',
  'MVDr\\.',
  'MDDr\\.',
  'PharmDr\\.',
  'JUDr\\.',
  'RNDr\\.',
  'PaedDr\\.',
  'PhDr\\.',
  'ThDr\\.',
  'RSDr\\.',
  'Ing\\. arch\\.',
  'Ing\\.',
  'Mgr\\.',
  'Bc\\.',
  'Mag\\.',
];
const TRAILING_TITLES = ['PhD\\.?', 'CSc\\.?', 'DrSc\\.?', 'MBA', 'MPH', 'ArtD\\.?'];

const LEADING_TITLE_REGEX = new RegExp(
  `^(?:(?:${LEADING_TITLES.join('|')})\\s*)+`,
  'i'
);
const TRAILING_TITLE_REGEX = new RegExp(
  `,?\\s*(?:${TRAILING_TITLES.join('|')})\\s*$`,
  'i'
);

/** Removes leading/trailing academic titles from a full name. */
export function stripTitles(fullName) {
  if (!fullName) return '';
  let name = fullName.trim();
  name = name.replace(LEADING_TITLE_REGEX, '').trim();
  name = name.replace(TRAILING_TITLE_REGEX, '').trim();
  return name;
}

/**
 * "Peter Novák" -> "P. Novák"
 * "MUDr. Vladimír Kováč, PhD." -> "V. Kováč"
 * Single-word names (or empty input) are returned unchanged/empty.
 */
export function formatShortName(fullName) {
  const clean = stripTitles(fullName);
  if (!clean) return '';
  const parts = clean.split(/\s+/).filter(Boolean);
  if (parts.length < 2) return clean;
  const firstInitial = parts[0].charAt(0).toUpperCase();
  const surname = parts[parts.length - 1];
  return `${firstInitial}. ${surname}`;
}

/**
 * The three ways a name is written on the printed rota.
 *
 * 'short'  -> "P. Novák"                     (initial + surname, no titles)
 * 'full'   -> "Peter Novák"                  (whole name, titles stripped)
 * 'titles' -> "MUDr. Peter Novák, PhD."      (exactly as it is on record)
 *
 * An unknown style is read as 'short', and a name that a style would empty
 * falls back to what was given, so a square never comes out blank.
 */
export function formatNameStyle(fullName, style) {
  if (!fullName) return '';
  if (style === 'titles') return fullName;
  if (style === 'full') return stripTitles(fullName) || fullName;
  return formatShortName(fullName) || fullName;
}
