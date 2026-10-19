/** Hues the custom days are told apart by, in the order they were created. */
const CUSTOM_DAY_HUES = [205, 145, 32, 275, 340, 185, 95, 0];

/** The hue of every custom day, by id. */
export const customDayHues = (customDays) => {
  const map = new Map();
  [...customDays]
    .sort((a, b) => a.id - b.id)
    .forEach((item, index) => map.set(item.id, CUSTOM_DAY_HUES[index % CUSTOM_DAY_HUES.length]));
  return map;
};

/** Inline style that tints an element with a custom day's hue. */
export const hueStyle = (hue) => (hue == null ? undefined : { '--cday-hue': hue });
