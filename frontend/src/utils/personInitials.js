import { stripTitles } from './formatEmployeeName';

/**
 * Two letters for a person's avatar: the first and the last word of the
 * name, academic titles left out.
 *
 * Taking the first character of the full name gave almost every doctor an
 * "M" (for "MUDr."), so a list of avatars said nothing. Words ending in a
 * dot are titles that stripTitles does not know ("PhD., MPH." after a
 * comma); anything not starting with a letter ("-" in a double surname)
 * is skipped too. A name without letters falls back to its first character.
 */
export function personInitials(name) {
  const words = stripTitles(name || '')
    .split(/[\s,]+/)
    .filter((word) => word && !word.endsWith('.') && /^\p{L}/u.test(word));
  if (words.length === 0) return (name || '?').trim().charAt(0).toUpperCase() || '?';
  const first = words[0].charAt(0);
  const last = words.length > 1 ? words[words.length - 1].charAt(0) : '';
  return `${first}${last}`.toUpperCase();
}
