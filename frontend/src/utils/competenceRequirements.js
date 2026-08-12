export const ISO_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

export const legacyRequiredCount = (column) =>
  Math.max(0, Number(column.required_count ?? column.count ?? 1));

/** Return a complete, sorted weekly definition for old and new API records. */
export const normalizeWeekdayRequirements = (column) => {
  const configured = new Map(
    (column.weekday_requirements || []).map((item) => [
      Number(item.weekday),
      Math.max(0, Number(item.required_count)),
    ])
  );
  const fallback = legacyRequiredCount(column);
  return ISO_WEEKDAYS.map((weekday) => ({
    weekday,
    required_count: configured.get(weekday) ?? fallback,
  }));
};

export const normalizeCompetenceRequirements = (column) => ({
  ...column,
  weekday_requirements: normalizeWeekdayRequirements(column),
});

const requirementMap = (column) =>
  new Map(
    normalizeWeekdayRequirements(column).map((item) => [
      item.weekday,
      item.required_count,
    ])
  );

const signatureForWeekday = (columns, weekday) =>
  [...columns]
    .sort((a, b) => a.id - b.id)
    .map((column) => `${column.id}:${requirementMap(column).get(weekday)}`)
    .join('|');

/** Collapse weekdays whose complete competence-demand vectors are identical. */
export const groupWeekdaysByRequirements = (columns) => {
  if (columns.length === 0) return [];
  const bySignature = new Map();
  ISO_WEEKDAYS.forEach((weekday) => {
    const signature = signatureForWeekday(columns, weekday);
    const current = bySignature.get(signature);
    if (current) current.weekdays.push(weekday);
    else {
      bySignature.set(signature, {
        id: `days-${weekday}`,
        weekdays: [weekday],
      });
    }
  });
  return [...bySignature.values()];
};

/** Merge existing UI groups when their current demand vectors become equal. */
export const mergeEquivalentDayGroups = (groups, columns) => {
  const merged = new Map();
  groups
    .filter((group) => group.weekdays.length > 0)
    .forEach((group) => {
      const signature = signatureForWeekday(columns, group.weekdays[0]);
      const current = merged.get(signature);
      if (current) current.weekdays.push(...group.weekdays);
      else merged.set(signature, { ...group, weekdays: [...group.weekdays] });
    });
  return [...merged.values()].map((group) => ({
    ...group,
    weekdays: [...new Set(group.weekdays)].sort((a, b) => a - b),
  }));
};

/** Apply one group's edited count to each of its weekdays. */
export const updateGroupRequiredCount = (
  columns,
  competenceId,
  weekdays,
  requiredCount
) => {
  const weekdaySet = new Set(weekdays);
  return columns.map((column) => {
    if (column.id !== competenceId) return column;
    return {
      ...column,
      weekday_requirements: normalizeWeekdayRequirements(column).map((item) =>
        weekdaySet.has(item.weekday)
          ? { ...item, required_count: Math.max(0, Number(requiredCount)) }
          : item
      ),
    };
  });
};

/** Split a non-empty proper subset of weekdays into a new editable row. */
export const splitDayGroup = (groups, groupId, selectedWeekdays) => {
  const selected = [...new Set(selectedWeekdays)].sort((a, b) => a - b);
  const source = groups.find((group) => group.id === groupId);
  if (!source || selected.length === 0 || selected.length >= source.weekdays.length) {
    return groups;
  }
  const selectedSet = new Set(selected);
  const remaining = source.weekdays.filter((weekday) => !selectedSet.has(weekday));
  const nextId = `${groupId}-split-${selected.join('-')}`;
  return groups.flatMap((group) =>
    group.id === groupId
      ? [
          { ...group, weekdays: remaining },
          { id: nextId, weekdays: selected },
        ]
      : [group]
  );
};

export const requiredCountForGroup = (column, group) => {
  const byWeekday = requirementMap(column);
  return byWeekday.get(group.weekdays[0]) ?? legacyRequiredCount(column);
};

/** Semantic fingerprint: UI grouping itself is irrelevant, per-day values are not. */
export const fingerprintCompetenceRequirements = (columns) =>
  JSON.stringify(
    [...columns]
      .map((column) => ({
        id: column.id,
        weekday_requirements: normalizeWeekdayRequirements(column),
      }))
      .sort((a, b) => a.id - b.id)
  );
