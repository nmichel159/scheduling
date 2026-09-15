import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  approveAmbulanceSchedule,
  fetchMonthlyScheduleOverview,
  generateAmbulanceSchedule,
  updateAmbulanceSchedule,
} from '../services/scheduleService';
import ConfirmDialog from '../components/ConfirmDialog';
import GenerationProgressDialog from '../components/GenerationProgressDialog';
import { formatDurationSeconds } from '../utils/generationEstimate';
import { generationErrorMessage } from '../utils/generationIssues';
import './ScheduleOverviewView.css';

const shiftedMonth = ({ y, m }, offset) => {
  const value = new Date(y, m + offset, 1);
  return { y: value.getFullYear(), m: value.getMonth() };
};

/** Which of the three states one ambulance-month is in. */
const statusOf = (row) => {
  if (row.shift_count === 0) return 'missing';
  return row.is_approved ? 'approved' : 'draft';
};

/**
 * Hospital-wide schedule overview for administrators.
 *
 * Answers one question per workplace — is this month planned, is it only a
 * draft, or is nothing there at all — and lets the administrator close the
 * gaps without opening each workplace's editor.
 *
 * Read-only apart from two actions per row:
 *
 * - Generate runs the MILP solver and saves the result straight away. The
 *   manager's editor deliberately leaves the draft unsaved for review, but
 *   there is nothing to review it in here, and an unsaved draft would leave
 *   the row exactly as it was — so generating here is generate + save, and
 *   the confirmation says so.
 * - Approve publishes the saved month to its employees.
 *
 * Both go through the same endpoints the manager uses: the backend already
 * lets an administrator (role level >= 3) reach any ambulance, so there is no
 * separate admin-only write path.
 */
const ScheduleOverviewView = () => {
  const { t, i18n } = useTranslation();
  const today = useMemo(() => new Date(), []);

  const [view, setView] = useState({
    y: today.getFullYear(),
    m: today.getMonth(),
  });
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  // The ambulance a write is running for, so only its row locks up:
  //   { id, action: 'generate' | 'approve', name }
  const [busy, setBusy] = useState(null);
  const [confirmState, setConfirmState] = useState(null);

  const monthLabel = useMemo(() => {
    const formatter = new Intl.DateTimeFormat(
      i18n.language === 'en' ? 'en-GB' : 'sk-SK',
      { month: 'long', year: 'numeric' }
    );
    return formatter.format(new Date(view.y, view.m, 1));
  }, [view.y, view.m, i18n.language]);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMonthlyScheduleOverview({
        month: view.m + 1,
        year: view.y,
      });
      setRows(data.ambulances || []);
    } catch {
      setRows([]);
      setError(t('schedule_overview.load_error'));
    } finally {
      setLoading(false);
    }
  }, [t, view.m, view.y]);

  useEffect(() => {
    loadOverview();
  }, [loadOverview]);

  const isCurrentMonth =
    view.y === today.getFullYear() && view.m === today.getMonth();

  /** Step by `offset` months, or jump back to the running month when null. */
  const changeMonth = (offset) => {
    setMessage(null);
    setView((current) =>
      offset === null
        ? { y: today.getFullYear(), m: today.getMonth() }
        : shiftedMonth(current, offset)
    );
  };

  const approvedCount = rows.filter((row) => row.is_approved).length;
  const missingCount = rows.filter((row) => row.shift_count === 0).length;

  /* ---------- actions ---------- */

  const runGeneration = async (row) => {
    setBusy({
      id: row.ambulance_id,
      action: 'generate',
      name: row.ambulance_name,
    });
    setError(null);
    setMessage(null);
    const period = { month: view.m + 1, year: view.y };
    try {
      const result = await generateAmbulanceSchedule(row.ambulance_id, period);
      // Persist immediately: this screen has no editor to review a draft in,
      // and an unsaved draft could not be approved afterwards.
      await updateAmbulanceSchedule(
        row.ambulance_id,
        result.entries.map((entry) => ({
          user_id: entry.user_id,
          competence_id: entry.competence_id,
          work_date: entry.work_date,
        })),
        period
      );
      setMessage(
        t('schedule_overview.generate_success', {
          ambulance: row.ambulance_name,
          count: result.assignment_count,
        })
      );
      await loadOverview();
    } catch (err) {
      setError(`${row.ambulance_name}: ${generationErrorMessage(err, t)}`);
    } finally {
      setBusy(null);
    }
  };

  // Generation always asks first: it replaces the whole month for that
  // workplace, including one its manager may have already built by hand.
  const handleGenerate = (row) => {
    if (busy) return;
    setConfirmState({
      message:
        row.shift_count > 0
          ? t('schedule_overview.generate_confirm_replace', {
              ambulance: row.ambulance_name,
              month: monthLabel,
            })
          : t('schedule_overview.generate_confirm', {
              ambulance: row.ambulance_name,
              month: monthLabel,
            }),
      details: t('schedule_overview.generate_confirm_saves'),
      confirmLabel: t('schedule_overview.generate'),
      cancelLabel: t('schedule_overview.cancel'),
      onConfirm: () => {
        setConfirmState(null);
        runGeneration(row);
      },
      onCancel: () => setConfirmState(null),
    });
  };

  const runApproval = async (row) => {
    setBusy({
      id: row.ambulance_id,
      action: 'approve',
      name: row.ambulance_name,
    });
    setError(null);
    setMessage(null);
    try {
      await approveAmbulanceSchedule(row.ambulance_id, {
        month: view.m + 1,
        year: view.y,
      });
      setMessage(
        t('schedule_overview.approve_success', { ambulance: row.ambulance_name })
      );
      await loadOverview();
    } catch (err) {
      // 409 means the saved month disappeared since this list was loaded, so
      // the row on screen is stale — reload instead of leaving a button that
      // keeps failing.
      if (err?.response?.status === 409) {
        await loadOverview();
        setError(
          t('schedule_overview.approve_empty_error', {
            ambulance: row.ambulance_name,
          })
        );
        return;
      }
      setError(
        t('schedule_overview.approve_error', { ambulance: row.ambulance_name })
      );
    } finally {
      setBusy(null);
    }
  };

  const handleApprove = (row) => {
    if (busy) return;
    setConfirmState({
      message: t('schedule_overview.approve_confirm', {
        ambulance: row.ambulance_name,
        month: monthLabel,
      }),
      confirmLabel: t('schedule_overview.approve'),
      cancelLabel: t('schedule_overview.cancel'),
      onConfirm: () => {
        setConfirmState(null);
        runApproval(row);
      },
      onCancel: () => setConfirmState(null),
    });
  };

  /* ---------- render ---------- */

  return (
    <div className="overview">
      {error && <div className="overview-banner is-error">{error}</div>}
      {message && <div className="overview-banner is-success">{message}</div>}

      <div className="overview-topbar">
        <div className="overview-month-navigation">
          <button
            type="button"
            className="overview-month-button"
            onClick={() => changeMonth(-1)}
            disabled={loading || !!busy}
            aria-label={t('schedule_overview.previous_month')}
          >
            &#8249;
          </button>
          <span className="overview-month">{monthLabel}</span>
          <button
            type="button"
            className="overview-month-button"
            onClick={() => changeMonth(1)}
            disabled={loading || !!busy}
            aria-label={t('schedule_overview.next_month')}
          >
            &#8250;
          </button>
          {/* Months are unbounded in both directions, so after browsing a year
              back there is no cheap way home without this. */}
          {!isCurrentMonth && (
            <button
              type="button"
              className="overview-month-today"
              onClick={() => changeMonth(null)}
              disabled={loading || !!busy}
            >
              {t('schedule_overview.current_month')}
            </button>
          )}
        </div>

        {rows.length > 0 && (
          <div className="overview-summary">
            <span className="overview-summary-item">
              {t('schedule_overview.summary_approved', {
                approved: approvedCount,
                total: rows.length,
              })}
            </span>
            {missingCount > 0 && (
              <span className="overview-summary-item is-warn">
                {t('schedule_overview.summary_missing', {
                  missing: missingCount,
                })}
              </span>
            )}
          </div>
        )}
      </div>

      <div className={`overview-card ${loading ? 'is-loading' : ''}`}>
        {rows.length === 0 ? (
          <p className="overview-empty">
            {loading
              ? t('schedule_overview.loading')
              : t('schedule_overview.empty')}
          </p>
        ) : (
          <table className="overview-table">
            <thead>
              <tr>
                <th scope="col">{t('schedule_overview.workplace')}</th>
                <th scope="col">{t('schedule_overview.manager')}</th>
                <th scope="col">{t('schedule_overview.status')}</th>
                <th scope="col" className="overview-num">
                  {t('schedule_overview.shifts')}
                </th>
                {/* Deliberately unlabelled: the buttons name themselves, and
                    a heading over them would only add a word that says
                    nothing. The cell itself has to stay for the column count. */}
                <th scope="col" className="overview-actions-head" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const status = statusOf(row);
                const rowBusy = busy?.id === row.ambulance_id;
                return (
                  <tr key={row.ambulance_id}>
                    <th scope="row" className="overview-name">
                      {row.ambulance_name}
                    </th>
                    <td className="overview-manager">
                      {row.manager_full_name || row.manager_email || (
                        <span className="overview-none">
                          {t('schedule_overview.no_manager')}
                        </span>
                      )}
                    </td>
                    <td>
                      <span className={`overview-status is-${status}`}>
                        <span className="overview-dot" aria-hidden="true" />
                        {t(`schedule_overview.status_${status}`)}
                      </span>
                    </td>
                    <td className="overview-num">
                      {row.shift_count > 0 ? (
                        row.shift_count
                      ) : (
                        <span className="overview-none">&#8211;</span>
                      )}
                    </td>
                    <td className="overview-actions">
                      {status === 'draft' && (
                        <button
                          type="button"
                          className="overview-btn overview-btn-approve"
                          onClick={() => handleApprove(row)}
                          disabled={!!busy || loading}
                        >
                          {rowBusy && busy.action === 'approve'
                            ? t('schedule_overview.approving')
                            : t('schedule_overview.approve')}
                        </button>
                      )}
                      <button
                        type="button"
                        className="overview-btn overview-btn-generate"
                        onClick={() => handleGenerate(row)}
                        disabled={!!busy || loading}
                      >
                        {rowBusy && busy.action === 'generate'
                          ? t('schedule_overview.generating')
                          : row.shift_count > 0
                            ? t('schedule_overview.regenerate')
                            : t('schedule_overview.generate')}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmState}
        message={confirmState?.message}
        details={confirmState?.details}
        confirmLabel={confirmState?.confirmLabel}
        cancelLabel={confirmState?.cancelLabel}
        onConfirm={confirmState?.onConfirm}
        onCancel={confirmState?.onCancel}
      />
      {/* No time estimate here: it is derived from the employees and
          competences of one ambulance, which this screen never loads. */}
      <GenerationProgressDialog
        open={busy?.action === 'generate'}
        title={t('schedule_overview.generating_title')}
        body={t('schedule_overview.generating_body', {
          ambulance: busy?.name || '',
          month: monthLabel,
        })}
        estimateLabel={null}
        elapsedLabel={(seconds) =>
          t('schedule_edit.generating_elapsed', {
            duration: formatDurationSeconds(seconds, t),
          })
        }
      />
    </div>
  );
};

export default ScheduleOverviewView;
