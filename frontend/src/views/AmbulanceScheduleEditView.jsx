import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useBlocker } from 'react-router-dom';
import {
  fetchCompetences,
  fetchEmployeeCompetenceTable,
} from '../services/competenceService';
import {
  approveAmbulanceSchedule,
  fetchAmbulanceSchedule,
  generateAmbulanceSchedule,
  updateAmbulanceSchedule,
} from '../services/scheduleService';
import { fetchSpecialDays } from '../services/specialDayService';
import { useWorkplace, useWorkplaceSwitchGuard } from '../hooks/workplaceContext';
import ScheduleListView from '../components/ScheduleListView';
import SchedulePlannerView from '../components/SchedulePlannerView';
import CompetenceCoverage from '../components/CompetenceCoverage';
import ConfirmDialog from '../components/ConfirmDialog';
import GenerationProgressDialog from '../components/GenerationProgressDialog';
import {
  displayedGenerationSeconds,
  formatDurationSeconds,
} from '../utils/generationEstimate';
import { generationErrorMessage } from '../utils/generationIssues';
import { formatShortName } from '../utils/formatEmployeeName';
import './AmbulanceScheduleEditView.css';

const pad = (n) => String(n).padStart(2, '0');
const isoDate = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
const isoWeekday = (dateObj) => (dateObj.getDay() + 6) % 7;
const shiftedMonth = ({ y, m }, offset) => {
  const value = new Date(y, m + offset, 1);
  return { y: value.getFullYear(), m: value.getMonth() };
};

/**
 * Fixed palette assigned to competences by their order (sorted by id).
 * Type 1 = blue, type 2 = red, ... per CALL 05. Cycles if there are more
 * competences than colors.
 */
const COMPETENCE_COLORS = [
  '#4f8ef7', // blue
  '#ef5350', // red
  '#66bb6a', // green
  '#ffb74d', // orange
  '#ab47bc', // purple
  '#26c6da', // cyan
  '#ec407a', // pink
  '#d4e157', // lime
  '#8d6e63', // brown
  '#78909c', // grey-blue
];
const FALLBACK_COLOR = '#9e9e9e';

/**
 * Local-only id for shifts that don't exist in the DB yet.
 * The bulk PUT /ambulances/{id}/schedule uses (user_id, competence_id, work_date)
 * as the entry key — the numeric `id` on our list is only a React key. After a
 * successful save we reload from GET, which replaces temp ids with real ones.
 */
const makeTempShiftId = () => `new-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const isTempShiftId = (id) => typeof id === 'string' && id.startsWith('new-');

function buildMonthCells(year, month) {
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const offset = isoWeekday(new Date(year, month, 1));
  const cells = [];
  for (let i = 0; i < offset; i += 1) cells.push(null);
  for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}

/**
 * Editable ambulance schedule.
 * - Top action bar (ambulance name + month, save/cancel) instead of a page header.
 * - Competence map under the ambulance list: color legend ordered by competence id.
 * - Each day cell lists employees as colored chips (color = competence),
 *   ordered by the competence map; chips are draggable between days.
 * - Clicking a chip opens the shift editor: pick a competence, pick a person.
 *   Changing the competence to one the current person can't do clears the
 *   person and only shows eligible candidates.
 * - Each day cell also exposes a "+" affordance that opens the same editor
 *   with an empty draft for that day.
 * - All edits stay in local state and are committed as a single bulk save
 *   through PUT /ambulances/{id}/schedule.
 */
const AmbulanceScheduleEditView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  // Which workplace is being scheduled comes from the header switcher.
  const {
    activeId: selectedId,
    active: selected,
    loading: workplacesLoading,
    error: workplacesError,
  } = useWorkplace();

  const [competences, setCompetences] = useState([]);
  const [employees, setEmployees] = useState([]); // [{user_id, email, full_name, competences:[{id,name}]}]
  const [shifts, setShifts] = useState([]); // Mutable during editing
  const [originalShifts, setOriginalShifts] = useState([]); // Baseline for dirty check
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [approving, setApproving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [generationMessage, setGenerationMessage] = useState(null);
  // Pending confirmation dialog: { message, onConfirm, onCancel }.
  const [confirmState, setConfirmState] = useState(null);
  const [draggedShift, setDraggedShift] = useState(null);
  const [dragOverDate, setDragOverDate] = useState(null);
  // Only the planner is on screen for now; the calendar and list branches
  // below stay put so the switcher can come back without a rewrite.
  const scheduleView = 'planner';
  // ISO dates this workplace rests on, for the year on screen. A duty on one
  // of them is staffed and paid from the competence's day-of-rest column
  // rather than from the weekday it lands on, which is how the generator
  // reads it -- so the planner has to know them to agree with the solver.
  const [restDays, setRestDays] = useState(() => new Set());

  // Shift editor state.
  //   editingShift: the shift being edited (or a fresh one when isNew=true).
  //   draftCompetenceId / draftUserId: the current selection inside the popup.
  const [editingShift, setEditingShift] = useState(null);
  const [draftCompetenceId, setDraftCompetenceId] = useState(null);
  const [draftUserId, setDraftUserId] = useState(null);

  const [view, setView] = useState({
    y: today.getFullYear(),
    m: today.getMonth(),
  });

  // Only the newest load may publish its result. Switching ambulance or month
  // leaves the previous request in flight; without this guard a slower earlier
  // response overwrites the current one and `shifts` ends up describing a
  // different ambulance-month than the toolbar does -- approving then posts a
  // period the backend has no rows for and answers 409.
  const loadRequestId = useRef(0);

  const loadSchedule = useCallback(async () => {
    if (!selectedId) return;
    const requestId = loadRequestId.current + 1;
    loadRequestId.current = requestId;
    setLoading(true);
    setError(null);
    setGenerationMessage(null);
    try {
      const [scheduleData, competenceData, employeeData] = await Promise.all([
        fetchAmbulanceSchedule(selectedId, { month: view.m + 1, year: view.y }),
        fetchCompetences(selectedId),
        fetchEmployeeCompetenceTable(selectedId),
      ]);
      if (loadRequestId.current !== requestId) return;
      setShifts(scheduleData);
      setOriginalShifts(scheduleData);
      setCompetences(competenceData);
      setEmployees(employeeData);
    } catch {
      if (loadRequestId.current !== requestId) return;
      // Drop the stale rows too: showing the previous period's schedule under
      // the new heading is worse than showing an empty one with the error.
      setShifts([]);
      setOriginalShifts([]);
      setError(t('schedule_edit.load_schedule_error'));
    } finally {
      if (loadRequestId.current === requestId) setLoading(false);
    }
  }, [selectedId, t, view.m, view.y]);

  useEffect(() => {
    loadSchedule();
  }, [loadSchedule]);

  /* The special-day calendar is a year at a time and changes far less often
     than the month does, so it loads on its own. A failure is left silent:
     the schedule is still fully editable without it, only the day-of-rest
     columns fall back to the weekday ones. */
  useEffect(() => {
    if (!selectedId) {
      setRestDays(new Set());
      return undefined;
    }
    let active = true;
    fetchSpecialDays(selectedId, view.y)
      .then((data) => {
        if (!active) return;
        setRestDays(
          new Set(
            (data.entries || [])
              .filter((entry) => entry.is_rest_day)
              .map((entry) => entry.day)
          )
        );
      })
      .catch(() => {
        if (active) setRestDays(new Set());
      });
    return () => {
      active = false;
    };
  }, [selectedId, view.y]);

  /* --- Competence map: order + colors by competence id --- */

  const competenceMap = useMemo(() => {
    const sorted = [...competences].sort((a, b) => a.id - b.id);
    const map = {};
    sorted.forEach((c, idx) => {
      map[c.id] = {
        ...c,
        order: idx,
        color: COMPETENCE_COLORS[idx % COMPETENCE_COLORS.length],
      };
    });
    return map;
  }, [competences]);

  const legend = useMemo(
    () => Object.values(competenceMap).sort((a, b) => a.order - b.order),
    [competenceMap]
  );

  const competenceColor = (competenceId) =>
    competenceMap[competenceId]?.color || FALLBACK_COLOR;

  const competenceOrder = (competenceId) =>
    competenceMap[competenceId]?.order ?? Number.MAX_SAFE_INTEGER;

  const employeeById = useMemo(() => {
    const map = new Map();
    employees.forEach((e) => map.set(e.user_id, e));
    return map;
  }, [employees]);

  const isDirty = useMemo(
    () => JSON.stringify(shifts) !== JSON.stringify(originalShifts),
    [shifts, originalShifts]
  );
  // Let the switcher warn before it pulls another workplace under the editor.
  useWorkplaceSwitchGuard(isDirty);

  const isApproved = useMemo(
    () =>
      !isDirty &&
      shifts.length > 0 &&
      shifts.every((shift) => shift.is_approved === true),
    [isDirty, shifts]
  );

  /* ---------- leave-page guards while there are unsaved changes ---------- */

  // Browser-level guard: closing the tab / hard reload / typing another URL.
  useEffect(() => {
    const handler = (e) => {
      if (!isDirty) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  // Router-level guard: clicking another item in the sidebar.
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }) =>
        isDirty && currentLocation.pathname !== nextLocation.pathname,
      [isDirty]
    )
  );

  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    setConfirmState({
      message: t('schedule_edit.unsaved_warning'),
      onConfirm: () => {
        setConfirmState(null);
        blocker.proceed();
      },
      onCancel: () => {
        setConfirmState(null);
        blocker.reset();
      },
    });
  }, [blocker, t]);

  const shiftsByDate = useMemo(() => {
    const map = {};
    shifts.forEach((s) => {
      (map[s.work_date] = map[s.work_date] || []).push(s);
    });
    // Order employees inside each day by the competence map order, then name.
    Object.values(map).forEach((list) =>
      list.sort(
        (a, b) =>
          competenceOrder(a.competence_id) - competenceOrder(b.competence_id) ||
          (a.user_full_name || '').localeCompare(b.user_full_name || '')
      )
    );
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shifts, competenceMap]);

  const cells = useMemo(() => buildMonthCells(view.y, view.m), [view.y, view.m]);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(i18n.language === 'en' ? 'en-GB' : 'sk-SK', {
      month: 'long',
      year: 'numeric',
    });
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, i18n.language]);

  /* The first date the manager may still change: tomorrow, or the 1st for a
   * month that has not started yet. Today and every day before it are already
   * worked or being worked, so neither Clear nor the solver may touch them —
   * regenerating a running month rewrites its remainder, not its history.
   * null means the whole displayed month lies in the past. */
  const firstEditableDate = useMemo(() => {
    const monthStart = new Date(view.y, view.m, 1);
    const monthEnd = new Date(view.y, view.m + 1, 0);
    const tomorrow = new Date(
      today.getFullYear(),
      today.getMonth(),
      today.getDate() + 1
    );
    const from = tomorrow > monthStart ? tomorrow : monthStart;
    if (from > monthEnd) return null;
    return isoDate(from.getFullYear(), from.getMonth(), from.getDate());
  }, [today, view.m, view.y]);

  // ISO dates sort lexicographically, so a plain string compare separates the
  // editable tail of the month from its locked head.
  const isEditableDate = useCallback(
    (dateStr) => firstEditableDate != null && dateStr >= firstEditableDate,
    [firstEditableDate]
  );

  const hasClearableShifts = useMemo(
    () => shifts.some((shift) => isEditableDate(shift.work_date)),
    [isEditableDate, shifts]
  );

  // Shown before the solve starts, so the manager can decide whether to wait.
  // Derived from the employees and competences already on screen -- see
  // utils/generationEstimate.js for the calibration and the safety factor.
  const estimateLabel = useMemo(() => {
    const seconds = displayedGenerationSeconds(employees, competences, view.y, view.m);
    if (seconds === 0) return null;
    return formatDurationSeconds(seconds, t);
  }, [employees, competences, view.y, view.m, t]);

  const dayLabels = useMemo(
    () => [0, 1, 2, 3, 4, 5, 6].map((i) => t(`workload.days.${i}`)),
    [t]
  );


  /* --- Shift editor: derived selection state --- */

  // Employees who can perform the currently drafted competence in this ambulance.
  const eligibleEmployees = useMemo(() => {
    if (draftCompetenceId == null) return [];
    return employees.filter((e) =>
      (e.competences || []).some((c) => c.id === draftCompetenceId)
    );
  }, [employees, draftCompetenceId]);

  // Reset the draft whenever the editor opens on a new shift.
  useEffect(() => {
    if (editingShift) {
      setDraftCompetenceId(editingShift.competence_id ?? null);
      setDraftUserId(editingShift.user_id ?? null);
    } else {
      setDraftCompetenceId(null);
      setDraftUserId(null);
    }
  }, [editingShift]);

  // Close the popup on Escape.
  useEffect(() => {
    if (!editingShift) return undefined;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setEditingShift(null);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [editingShift]);

  /* --- Drag and drop --- */

  const handleDragStart = (e, shift, sourceDate) => {
    setDraggedShift({ shift, sourceDate });
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDragEnter = (e, date) => {
    setDragOverDate(date);
  };

  const handleDragLeave = (e) => {
    if (e.currentTarget === e.target) {
      setDragOverDate(null);
    }
  };

  const handleDrop = (e, targetDate) => {
    e.preventDefault();
    setDragOverDate(null);

    if (!draggedShift) return;
    const { shift, sourceDate } = draggedShift;

    if (sourceDate === targetDate) {
      setDraggedShift(null);
      return; // No change
    }

    // Move the shift to the new date (persisted on save; the employee's
    // personal calendar reflects the change automatically after save).
    setShifts((prev) =>
      prev.map((s) => (s.id === shift.id ? { ...s, work_date: targetDate } : s))
    );
    setDraggedShift(null);
  };

  const handleRemoveShift = (shiftId) => {
    setShifts((prev) => prev.filter((s) => s.id !== shiftId));
  };

  /* One-click assignment, used by the planner's people list: it already knows
   * the day, the competence and the person, so it needs no editor popup. The
   * same (user, competence, day) twice is the bulk PUT's own entry key, so a
   * duplicate would be silently collapsed on save — refuse it here instead. */
  const handleAssignShift = (dateStr, competenceId, userId) => {
    const emp = employeeById.get(userId);
    const comp = competenceMap[competenceId];
    setShifts((prev) => {
      const exists = prev.some(
        (s) =>
          s.work_date === dateStr &&
          s.competence_id === competenceId &&
          s.user_id === userId
      );
      if (exists) return prev;
      return [
        ...prev,
        {
          id: makeTempShiftId(),
          ambulance_id: selectedId,
          work_date: dateStr,
          user_id: userId,
          competence_id: competenceId,
          user_full_name: emp?.full_name || emp?.email || '',
          user_email: emp?.email || '',
          competence_name: comp?.name || '',
        },
      ];
    });
  };

  /** Step by `offset` months, or jump back to the running month when null. */
  const changeMonth = (offset) => {
    const applyChange = () => {
      setGenerationMessage(null);
      setView((current) =>
        offset === null
          ? { y: today.getFullYear(), m: today.getMonth() }
          : shiftedMonth(current, offset)
      );
    };
    if (!isDirty) {
      applyChange();
      return;
    }
    setConfirmState({
      message: t('schedule_edit.unsaved_warning'),
      onConfirm: () => {
        setConfirmState(null);
        applyChange();
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const generateSchedule = async () => {
    setGenerating(true);
    setError(null);
    setGenerationMessage(null);
    try {
      // Everything on screen is handed to the solver as fixed: the locked head
      // of the month because it is history, and whatever the manager placed
      // himself because that is the instruction. Clear is what empties the
      // editable tail before a full regeneration.
      const fixedEntries = shifts
        .filter((shift) => shift.user_id != null && shift.competence_id != null)
        .map((shift) => ({
          user_id: shift.user_id,
          competence_id: shift.competence_id,
          work_date: shift.work_date,
        }));
      const result = await generateAmbulanceSchedule(
        selectedId,
        { month: view.m + 1, year: view.y },
        { fixed_entries: fixedEntries, generate_from: firstEditableDate }
      );
      setShifts(
        result.entries.map((entry, index) => ({
          ...entry,
          id: `new-generated-${selectedId}-${index}`,
        }))
      );
      setEditingShift(null);
      setGenerationMessage(
        t('schedule_edit.generate_success', { count: result.assignment_count })
      );
    } catch (err) {
      setError(generationErrorMessage(err, t));
    } finally {
      setGenerating(false);
    }
  };

  // Generation always asks first, even with nothing unsaved: it discards the
  // whole month that is on screen -- including a schedule the manager already
  // saved -- and the solve cannot be undone or cancelled once it starts.
  const handleGenerate = () => {
    if (!selectedId || generating || loading || saving || approving) return;
    if (firstEditableDate == null) return;
    const warning = t('schedule_edit.generate_confirm', {
      ambulance: selected?.name || '',
      month: monthLabel,
    });
    setConfirmState({
      message: isDirty
        ? `${warning} ${t('schedule_edit.generate_confirm_unsaved')}`
        : warning,
      details: estimateLabel
        ? t('schedule_edit.generate_confirm_estimate', { duration: estimateLabel })
        : null,
      confirmLabel: t('schedule_edit.generate'),
      cancelLabel: t('schedule_edit.editor_cancel'),
      onConfirm: () => {
        setConfirmState(null);
        generateSchedule();
      },
      onCancel: () => setConfirmState(null),
    });
  };

  /* Empty the part of the month that may still be planned. It is a local
   * edit like any other: the manager sees the empty days, can generate into
   * them, and nothing reaches the database until Save. */
  const clearSchedule = () => {
    setShifts((prev) => prev.filter((shift) => !isEditableDate(shift.work_date)));
    setEditingShift(null);
    setGenerationMessage(null);
  };

  const handleClear = () => {
    if (!selectedId || generating || loading || saving || approving) return;
    if (firstEditableDate == null) return;
    if (!shifts.some((shift) => isEditableDate(shift.work_date))) return;
    setConfirmState({
      message: t('schedule_edit.clear_confirm', {
        ambulance: selected?.name || '',
        month: monthLabel,
      }),
      confirmLabel: t('schedule_edit.clear'),
      cancelLabel: t('schedule_edit.editor_cancel'),
      onConfirm: () => {
        setConfirmState(null);
        clearSchedule();
      },
      onCancel: () => setConfirmState(null),
    });
  };

  /* --- Shift editor: actions --- */

  // Change of competence inside the editor.
  //   If the currently drafted person can't perform the new competence,
  //   clear the person: the caller (per CALL 05) wants the name to disappear
  //   and the picker to only offer eligible candidates.
  const handleDraftCompetenceChange = (nextCompetenceId) => {
    setDraftCompetenceId(nextCompetenceId);
    if (nextCompetenceId == null) {
      setDraftUserId(null);
      return;
    }
    if (draftUserId != null) {
      const emp = employeeById.get(draftUserId);
      const canDo = emp?.competences?.some((c) => c.id === nextCompetenceId);
      if (!canDo) setDraftUserId(null);
    }
  };

  // Commit the popup draft back into local `shifts` state. No API call —
  // persistence happens through the global "Save schedule" button.
  const handleEditorSave = () => {
    if (!editingShift || draftCompetenceId == null || draftUserId == null) return;
    const emp = employeeById.get(draftUserId);
    const comp = competenceMap[draftCompetenceId];
    const patched = {
      ...editingShift,
      user_id: draftUserId,
      competence_id: draftCompetenceId,
      user_full_name: emp?.full_name || emp?.email || '',
      user_email: emp?.email || '',
      competence_name: comp?.name || '',
    };
    setShifts((prev) => {
      if (editingShift.isNew) {
        return [...prev, patched];
      }
      return prev.map((s) => (s.id === editingShift.id ? patched : s));
    });
    setEditingShift(null);
  };

  const handleEditorDelete = () => {
    if (!editingShift) return;
    handleRemoveShift(editingShift.id);
    setEditingShift(null);
  };

  const openEditorForShift = (shift) => {
    setEditingShift({ ...shift, isNew: false });
  };

  const openEditorForNewShift = (dateStr) => {
    setEditingShift({
      id: makeTempShiftId(),
      ambulance_id: selectedId,
      work_date: dateStr,
      user_id: null,
      competence_id: null,
      user_full_name: '',
      user_email: '',
      competence_name: '',
      isNew: true,
    });
  };

  /* --- Save / cancel --- */

  const handleSave = async () => {
    if (!selectedId || !isDirty) return;
    setSaving(true);
    setError(null);
    try {
      // Filter out any entries that never got a person or competence assigned
      // (defensive — the editor blocks Save until both are set, but a stray
      // half-filled temp shift shouldn't be persisted).
      const entries = shifts
        .filter((s) => s.user_id != null && s.competence_id != null)
        .map((s) => ({
          user_id: s.user_id,
          competence_id: s.competence_id,
          work_date: s.work_date,
        }));
      await updateAmbulanceSchedule(selectedId, entries, {
        month: view.m + 1,
        year: view.y,
      });
      // After save, reload from GET so the state matches the backend exactly.
      // PUT returns ScheduleResponse (flat), but GET returns UserMonthlySchedule
      // (grouped by employee) which we already know how to flatten correctly.
      const fresh = await fetchAmbulanceSchedule(selectedId, {
        month: view.m + 1,
        year: view.y,
      });
      setShifts(fresh);
      setOriginalShifts(fresh);
      setGenerationMessage(null);
    } catch (err) {
       
      console.error('[schedule save]', err?.response?.status, err?.response?.data ?? err);
      setError(t('schedule_edit.save_error'));
    } finally {
      setSaving(false);
    }
  };

  const approveSchedule = async () => {
    setApproving(true);
    setError(null);
    try {
      await approveAmbulanceSchedule(selectedId, {
        month: view.m + 1,
        year: view.y,
      });
      const approvedShifts = shifts.map((shift) => ({
        ...shift,
        is_approved: true,
      }));
      setShifts(approvedShifts);
      setOriginalShifts(approvedShifts);
      setGenerationMessage(t('schedule_edit.approve_success'));
    } catch (err) {
      console.error('[schedule approve]', err?.response?.status, err?.response?.data ?? err);
      // 409 means the backend found no saved rows for this ambulance-month, so
      // whatever is on screen no longer matches the database. Reload instead of
      // leaving the phantom rows in place for a second failing attempt.
      if (err?.response?.status === 409) {
        // loadSchedule() clears `error` on entry, so set the message after it.
        await loadSchedule();
        setError(t('schedule_edit.approve_empty_error'));
        return;
      }
      setError(t('schedule_edit.approve_error'));
    } finally {
      setApproving(false);
    }
  };

  const handleApprove = () => {
    if (!selectedId || loading || isDirty || isApproved || shifts.length === 0) return;
    setConfirmState({
      message: t('schedule_edit.approve_warning'),
      confirmLabel: t('schedule_edit.approve'),
      onConfirm: () => {
        setConfirmState(null);
        approveSchedule();
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const handleCancel = () => {
    if (!isDirty) {
      setShifts(originalShifts);
      return;
    }
    setConfirmState({
      message: t('schedule_edit.unsaved_warning'),
      onConfirm: () => {
        setConfirmState(null);
        setShifts(originalShifts);
        setGenerationMessage(null);
      },
      onCancel: () => setConfirmState(null),
    });
  };

  if (workplacesLoading) {
    return (
      <div className="schedule-edit">
        <p>{t('schedule_edit.loading')}</p>
      </div>
    );
  }

  if (!selected) {
    return (
      <div className="schedule-edit">
        <p>
          {workplacesError
            ? t('schedule_edit.load_ambulances_error')
            : t('schedule_edit.no_ambulances')}
        </p>
      </div>
    );
  }

  const editorIsNew = editingShift?.isNew === true;
  const editorTitle = editorIsNew
    ? t('schedule_edit.add_shift_title')
    : t('schedule_edit.edit_shift_title');
  const canSaveEditor = draftCompetenceId != null && draftUserId != null;
  const showNoEligibleUsers =
    draftCompetenceId != null && eligibleEmployees.length === 0;

  /* The bar is one row: what you are looking at on the left, what you can do
   * to it on the right. It used to be two stacked rows, which read a little
   * calmer but cost some fifty pixels of height.
   *
   * It is built here rather than rendered in place because the planner puts
   * it somewhere else: there the day matrix owns the left column and has to
   * start at the very top of the page, so the bar goes into the right column
   * above the people calendar instead of lying across the whole width. */
  const topbar = (
    <div className="schedule-edit-topbar">
      <h1 className="schedule-edit-topbar-name">{selected.name}</h1>

      <div className="schedule-edit-state">
        <span
          className={`schedule-edit-pill ${isDirty ? 'is-dirty' : 'is-clean'}`}
        >
          <span className="schedule-edit-pill-dot" aria-hidden="true" />
          {isDirty ? t('schedule_edit.unsaved') : t('schedule_edit.saved')}
        </span>
        <span
          className={`schedule-edit-pill ${
            isApproved ? 'is-approved' : 'is-draft'
          }`}
        >
          <span className="schedule-edit-pill-dot" aria-hidden="true" />
          {isApproved
            ? t('schedule_edit.approved')
            : t('schedule_edit.not_approved')}
        </span>
      </div>

      <div className="schedule-edit-month-navigation">
        <button
          type="button"
          className="schedule-edit-month-button"
          onClick={() => changeMonth(-1)}
          disabled={loading || generating || saving || approving}
          aria-label={t('schedule_edit.previous_month')}
        >
          ‹
        </button>
        <span className="schedule-edit-topbar-month">{monthLabel}</span>
        <button
          type="button"
          className="schedule-edit-month-button"
          onClick={() => changeMonth(1)}
          disabled={loading || generating || saving || approving}
          aria-label={t('schedule_edit.next_month')}
        >
          ›
        </button>
      </div>

      <div className="schedule-edit-topbar-actions">
        {/* Only worth a place in the bar while there is something to
            throw away; permanently greyed out it just took room. */}
        {isDirty && (
          <button
            type="button"
            className="schedule-edit-btn schedule-edit-btn-cancel"
            onClick={handleCancel}
            disabled={approving}
          >
            {t('schedule_edit.cancel')}
          </button>
        )}
        <button
          type="button"
          className="schedule-edit-btn schedule-edit-btn-primary"
          onClick={handleSave}
          disabled={!isDirty || saving || approving}
        >
          {saving ? t('schedule_edit.saving') : t('schedule_edit.save')}
        </button>
        <button
          type="button"
          className="schedule-edit-btn schedule-edit-btn-approve"
          onClick={handleApprove}
          disabled={
            loading ||
            isDirty ||
            isApproved ||
            shifts.length === 0 ||
            saving ||
            generating ||
            approving
          }
        >
          {approving
            ? t('schedule_edit.approving')
            : t('schedule_edit.approve')}
        </button>
      </div>
    </div>
  );

  return (
    <div className="schedule-edit">
      {error && (
        <div className="schedule-edit-banner schedule-edit-banner-error">{error}</div>
      )}
      {generationMessage && (
        <div className="schedule-edit-banner schedule-edit-banner-success">
          {generationMessage}
        </div>
      )}

      {/* The planner carries its own generate button and shows the required
          head-counts inside its demand matrix, so the left rail would only
          repeat itself there — and the two halves of the split need the
          width far more than a second copy of the legend does. */}
      <div
        className={`schedule-edit-layout ${
          scheduleView === 'planner' ? 'is-wide' : 'is-single'
        }`}
      >
        {scheduleView !== 'planner' && (
        <nav className="schedule-edit-side">
          <div className="schedule-edit-generate-panel">
            <button
              type="button"
              className="schedule-edit-btn schedule-edit-btn-generate"
              onClick={handleGenerate}
              disabled={
                loading ||
                saving ||
                generating ||
                approving ||
                firstEditableDate == null
              }
            >
              {generating
                ? t('schedule_edit.generating')
                : t('schedule_edit.generate')}
            </button>
            <button
              type="button"
              className="schedule-edit-btn schedule-edit-btn-clear"
              onClick={handleClear}
              disabled={
                loading ||
                saving ||
                generating ||
                approving ||
                !hasClearableShifts
              }
            >
              {t('schedule_edit.clear')}
            </button>
            <span className="schedule-edit-generate-hint">
              {t('schedule_edit.generate_hint')}
            </span>
          </div>

          {/* Doubles as the colour -> competence map the legend used to be:
              same swatches in the same order as the calendar chips, with the
              per-day head-counts finally lined up into columns. */}
          <CompetenceCoverage
            competences={legend}
            emptyLabel={t('schedule_edit.legend_empty')}
          />
        </nav>
        )}

        <div className="schedule-edit-detail">
          {/* In planner mode the bar travels into the planner's own right
              column — see the comment on `topbar`. */}
          {scheduleView !== 'planner' && topbar}

          {scheduleView === 'calendar' && (
            <div className={`schedule-edit-grid ${loading ? 'is-loading' : ''}`}>
            {dayLabels.map((label) => (
              <div key={label} className="schedule-edit-grid-head">
                {label}
              </div>
            ))}

            {cells.map((day, idx) => {
              if (day == null) {
                return (
                  <div key={`e${idx}`} className="schedule-edit-cell schedule-edit-cell-empty" />
                );
              }

              const dateStr = isoDate(view.y, view.m, day);
              const dayShifts = shiftsByDate[dateStr] || [];
              const isToday = day === today.getDate();
              const isDragOver = dragOverDate === dateStr;

              return (
                <div
                  key={dateStr}
                  className={`schedule-edit-cell ${isToday ? 'is-today' : ''} ${
                    isDragOver ? 'is-drag-over' : ''
                  }`}
                  onDragOver={handleDragOver}
                  onDragEnter={(e) => handleDragEnter(e, dateStr)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, dateStr)}
                >
                  <div className="schedule-edit-cell-header">
                    <button
                      type="button"
                      className="schedule-edit-cell-add"
                      onClick={() => openEditorForNewShift(dateStr)}
                      title={t('schedule_edit.add_shift_title')}
                      aria-label={t('schedule_edit.add_shift_title')}
                    >
                      +
                    </button>
                    <span className="schedule-edit-cell-daynum">{day}</span>
                  </div>
                  <div className="schedule-edit-shifts">
                    {dayShifts.map((shift) => {
                      const color = competenceColor(shift.competence_id);
                      const isTemp = isTempShiftId(shift.id);
                      const fullLabel = shift.user_full_name || shift.user_email;
                      return (
                        <div
                          key={shift.id}
                          className={`schedule-edit-shift ${isTemp ? 'is-new' : ''}`}
                          style={{
                            borderLeftColor: color,
                            backgroundColor: `${color}26`,
                          }}
                          draggable
                          onDragStart={(e) => handleDragStart(e, shift, dateStr)}
                          onClick={() => openEditorForShift(shift)}
                        >
                          <span className="schedule-edit-shift-name-wrap">
                            <span className="schedule-edit-shift-name">
                              {formatShortName(shift.user_full_name) || shift.user_email}
                            </span>
                            {/* Custom hover tooltip: full name incl. titles,
                                shown after a short dwell so it doesn't flash
                                on quick mouse passes. */}
                            <span className="schedule-edit-shift-tooltip">
                              {fullLabel}
                            </span>
                          </span>
                          <button
                            type="button"
                            className="schedule-edit-shift-remove"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRemoveShift(shift.id);
                            }}
                            title={t('schedule_edit.remove_shift')}
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
            </div>
          )}

          {scheduleView === 'planner' && (
            <SchedulePlannerView
              header={topbar}
              year={view.y}
              month={view.m}
              today={today}
              locale={i18n.language === 'en' ? 'en-GB' : 'sk-SK'}
              weekdayLabels={dayLabels}
              competences={legend}
              employees={employees}
              shiftsByDate={shiftsByDate}
              restDays={restDays}
              competenceColor={competenceColor}
              loading={loading}
              onAssign={handleAssignShift}
              onRemoveShift={handleRemoveShift}
              onGenerate={handleGenerate}
              generateLabel={
                generating
                  ? t('schedule_edit.generating')
                  : t('schedule_edit.generate')
              }
              generateHint={t('schedule_edit.generate_hint')}
              generateDisabled={
                loading ||
                saving ||
                generating ||
                approving ||
                firstEditableDate == null
              }
              onClear={handleClear}
              clearLabel={t('schedule_edit.clear')}
              clearDisabled={
                loading ||
                saving ||
                generating ||
                approving ||
                !hasClearableShifts
              }
            />
          )}

          {scheduleView === 'list' && (
            <ScheduleListView
              year={view.y}
              month={view.m}
              locale={i18n.language === 'en' ? 'en-GB' : 'sk-SK'}
              today={today}
              shiftsByDate={shiftsByDate}
              competenceColor={competenceColor}
              loading={loading}
              dragOverDate={dragOverDate}
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onShiftClick={openEditorForShift}
              onShiftRemove={handleRemoveShift}
              onAddShift={openEditorForNewShift}
              removeShiftLabel={t('schedule_edit.remove_shift')}
              addShiftLabel={t('schedule_edit.add_shift_title')}
            />
          )}
        </div>
      </div>

      {editingShift && (
        <div
          className="schedule-edit-competence-popup-overlay"
          onClick={(e) => {
            if (e.target === e.currentTarget) setEditingShift(null);
          }}
        >
          <div
            className="schedule-edit-competence-popup schedule-edit-editor-popup"
            role="dialog"
            aria-modal="true"
          >
            <div className="schedule-edit-competence-popup-header">
              <div className="schedule-edit-popup-title-row">
                <span>{editorTitle}</span>
                <span className="schedule-edit-editor-date">{editingShift.work_date}</span>
              </div>
              <button
                type="button"
                className="schedule-edit-competence-popup-close"
                onClick={() => setEditingShift(null)}
                title={t('schedule_edit.close')}
              >
                ✕
              </button>
            </div>

            <div className="schedule-edit-editor-body">
              <div className="schedule-edit-editor-field is-centered">
                <span className="schedule-edit-editor-label">
                  {t('schedule_edit.competence_label')}
                </span>
                {/* Single-choice role picker. Rendered as square boxes laid out
                    side by side; `type="radio"` guarantees only one role can be
                    active at a time. Clicking the active one clears it again. */}
                <div
                  className="schedule-edit-role-options"
                  role="radiogroup"
                  aria-label={t('schedule_edit.competence_label')}
                >
                  {legend.length === 0 && (
                    <small className="schedule-edit-editor-hint">
                      {t('schedule_edit.legend_empty')}
                    </small>
                  )}
                  {legend.map((c) => {
                    const checked = draftCompetenceId === c.id;
                    return (
                      <label
                        key={c.id}
                        className={`schedule-edit-role-option ${checked ? 'is-checked' : ''}`}
                      >
                        <input
                          type="radio"
                          name="schedule-edit-role"
                          className="schedule-edit-role-input"
                          value={c.id}
                          checked={checked}
                          onChange={() => handleDraftCompetenceChange(c.id)}
                          onClick={() => {
                            // Allow unchecking the currently selected role.
                            if (checked) handleDraftCompetenceChange(null);
                          }}
                        />
                        <span className="schedule-edit-role-box" aria-hidden="true" />
                        <span
                          className="schedule-edit-editor-swatch"
                          style={{ backgroundColor: competenceColor(c.id) }}
                        />
                        <span className="schedule-edit-role-name">{c.name}</span>
                      </label>
                    );
                  })}
                </div>
              </div>

              <label className="schedule-edit-editor-field">
                <span className="schedule-edit-editor-label">
                  {t('schedule_edit.user_label')}
                </span>
                <select
                  className="schedule-edit-editor-select"
                  value={draftUserId ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value;
                    setDraftUserId(raw === '' ? null : Number(raw));
                  }}
                  disabled={draftCompetenceId == null || eligibleEmployees.length === 0}
                >
                  <option value="">
                    {draftCompetenceId == null
                      ? t('schedule_edit.pick_competence_first')
                      : t('schedule_edit.pick_user')}
                  </option>
                  {eligibleEmployees.map((e) => (
                    <option key={e.user_id} value={e.user_id}>
                      {e.full_name || e.email}
                    </option>
                  ))}
                </select>
                {showNoEligibleUsers && (
                  <small className="schedule-edit-editor-hint is-warn">
                    {t('schedule_edit.no_eligible_users')}
                  </small>
                )}
              </label>
            </div>

            <div className="schedule-edit-editor-footer">
              {!editorIsNew && (
                <button
                  type="button"
                  className="schedule-edit-btn schedule-edit-btn-danger"
                  onClick={handleEditorDelete}
                >
                  {t('schedule_edit.delete_shift')}
                </button>
              )}
              <div className="schedule-edit-editor-footer-spacer" />
              <button
                type="button"
                className="schedule-edit-btn"
                onClick={() => setEditingShift(null)}
              >
                {t('schedule_edit.editor_cancel')}
              </button>
              <button
                type="button"
                className="schedule-edit-btn schedule-edit-btn-primary"
                onClick={handleEditorSave}
                disabled={!canSaveEditor}
              >
                {t('schedule_edit.editor_apply')}
              </button>
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog
        open={!!confirmState}
        message={confirmState?.message}
        details={confirmState?.details}
        confirmLabel={confirmState?.confirmLabel || t('schedule_edit.leave_anyway')}
        cancelLabel={confirmState?.cancelLabel || t('schedule_edit.stay')}
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />
      {/* Closes on its own when generateSchedule() settles, uncovering the
          freshly generated month underneath. */}
      <GenerationProgressDialog
        open={generating}
        title={t('schedule_edit.generating_title')}
        body={t('schedule_edit.generating_body', {
          ambulance: selected?.name || '',
          month: monthLabel,
        })}
        estimateLabel={
          estimateLabel
            ? t('schedule_edit.generating_estimate', { duration: estimateLabel })
            : null
        }
        elapsedLabel={(seconds) =>
          t('schedule_edit.generating_elapsed', {
            duration: formatDurationSeconds(seconds, t),
          })
        }
      />
    </div>
  );
};

export default AmbulanceScheduleEditView;