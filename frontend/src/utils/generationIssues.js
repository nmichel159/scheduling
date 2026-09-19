/**
 * Human-readable text for the conflicts a failed schedule generation reports.
 *
 * The backend answers 409 with `detail.issues`, a machine-readable list of the
 * reasons the MILP model had no feasible solution (see
 * ScheduleGenerationError.as_detail()). Both the manager's schedule editor and
 * the admin overview trigger the same solve, so the wording lives here rather
 * than in either view.
 */

/** How many individual conflicts to spell out before summarizing the rest. */
const VISIBLE_ISSUE_LIMIT = 3;

/** One conflict as a sentence; unknown codes fall back to the generic reason. */
export const formatGenerationIssue = (issue, t) => {
  if (issue.code === 'insufficient_qualified_staff') {
    return t('schedule_edit.generate_shortage', {
      date: issue.work_date,
      competence: issue.competence_name,
      available: issue.available_count,
      required: issue.required_count,
    });
  }
  if (issue.code === 'insufficient_daily_capacity') {
    return t('schedule_edit.generate_daily_capacity', {
      date: issue.work_date,
      available: issue.available_count,
      required: issue.required_count,
    });
  }
  if (issue.code === 'insufficient_consecutive_day_rotation') {
    return t('schedule_edit.generate_rotation_shortage', {
      firstDate: issue.work_date,
      secondDate: issue.next_work_date,
      competence: issue.competence_name,
      available: issue.available_count,
      required: issue.required_count,
    });
  }
  if (issue.code === 'insufficient_consecutive_day_capacity') {
    return t('schedule_edit.generate_rest_shortage', {
      firstDate: issue.work_date,
      secondDate: issue.next_work_date,
      available: issue.available_count,
      required: issue.required_count,
    });
  }
  if (issue.code === 'fixed_assignment_over_requirement') {
    return t('schedule_edit.generate_fixed_over_requirement', {
      date: issue.work_date,
      competence: issue.competence_name,
      fixed: issue.fixed_count,
      required: issue.required_count,
    });
  }
  if (issue.code === 'fixed_assignment_rest_conflict') {
    return t('schedule_edit.generate_fixed_rest_conflict', {
      firstDate: issue.work_date,
      secondDate: issue.next_work_date,
    });
  }
  if (issue.code === 'fixed_assignment_unknown') {
    return t('schedule_edit.generate_fixed_unknown', {
      date: issue.work_date,
    });
  }
  if (issue.code === 'no_active_competences') {
    return t('schedule_edit.generate_no_competences');
  }
  if (issue.code === 'no_active_employees') {
    return t('schedule_edit.generate_no_employees');
  }
  return t('schedule_edit.generate_constraint_conflict');
};

/**
 * Whole banner text for a failed generation.
 *
 * Only the first few conflicts are spelled out — a month can fail on dozens of
 * days at once, and a banner listing all of them says less than one naming the
 * first three and counting the rest. Any failure without an issue list (a
 * network error, a 500) falls back to the generic message.
 *
 * @param {object} error Axios error from generateAmbulanceSchedule().
 * @param {Function} t i18next translate function.
 * @returns {string} Text ready to show in an error banner.
 */
export const generationErrorMessage = (error, t) => {
  const detail = error?.response?.data?.detail;
  const issues = Array.isArray(detail?.issues) ? detail.issues : [];
  if (issues.length === 0) return t('schedule_edit.generate_error');
  const visibleIssues = issues
    .slice(0, VISIBLE_ISSUE_LIMIT)
    .map((issue) => formatGenerationIssue(issue, t));
  const remainingCount = issues.length - visibleIssues.length;
  if (remainingCount > 0) {
    visibleIssues.push(
      t('schedule_edit.generate_more_issues', { count: remainingCount })
    );
  }
  return visibleIssues.join(' ');
};
