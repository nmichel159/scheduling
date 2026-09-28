import { useCallback, useId, useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import WorkloadCalendar from './WorkloadCalendar';
import { CloseIcon } from './NavIcons';
import { personInitials } from '../utils/personInitials';
import {
  createEmployeeUnavailability,
  deleteEmployeeUnavailability,
  fetchEmployeeMonthlyWish,
  fetchEmployeeUnavailabilities,
  saveEmployeeMonthlyWish,
  updateEmployeeUnavailability,
} from '../services/unavailabilityService';
import './EmployeeAvailabilityDialog.css';

/**
 * One employee's availability calendar, opened by their manager.
 *
 * The calendar itself is the same component the employee sees on
 * /workload; only the six functions it reads and writes through are
 * swapped for the workplace-scoped routes, which check that the caller
 * manages the workplace and that the person is one of its employees. A
 * day is therefore marked here exactly as the employee would mark it,
 * and the generator reads the result the same way.
 *
 * Every click writes immediately, the way the employee's own calendar
 * does, so there is nothing to save and closing loses nothing.
 *
 * Props:
 * - employee: { user_id, full_name, email } | null — null renders nothing
 * - ambulanceId: number
 * - onClose() — the opening screen reloads the month afterwards
 */
const EmployeeAvailabilityDialog = ({ employee, ambulanceId, onClose }) => {
  const { t } = useTranslation();
  const titleId = useId();
  const userId = employee ? employee.user_id : null;

  const fetchEntries = useCallback(
    (dateFrom, dateTo) =>
      fetchEmployeeUnavailabilities(ambulanceId, userId, dateFrom, dateTo),
    [ambulanceId, userId]
  );
  const createEntry = useCallback(
    (dateAbsent, reason) =>
      createEmployeeUnavailability(ambulanceId, userId, dateAbsent, reason),
    [ambulanceId, userId]
  );
  const updateEntry = useCallback(
    (id, reason) => updateEmployeeUnavailability(ambulanceId, userId, id, reason),
    [ambulanceId, userId]
  );
  const deleteEntry = useCallback(
    (id) => deleteEmployeeUnavailability(ambulanceId, userId, id),
    [ambulanceId, userId]
  );
  const loadWish = useCallback(
    () => fetchEmployeeMonthlyWish(ambulanceId, userId),
    [ambulanceId, userId]
  );
  const storeWish = useCallback(
    (value) => saveEmployeeMonthlyWish(ambulanceId, userId, value),
    [ambulanceId, userId]
  );

  /* A modal takes the focus while it is open — otherwise Tab keeps walking
   * the page behind the overlay — and hands it back to whatever opened it. */
  const dialogRef = useRef(null);
  const isOpen = !!employee;
  useLayoutEffect(() => {
    if (!isOpen) return undefined;
    const opener = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      if (opener && document.body.contains(opener)) opener.focus();
    };
  }, [isOpen]);

  useLayoutEffect(() => {
    if (!employee) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [employee, onClose]);

  if (!employee || ambulanceId == null) return null;

  const label = employee.full_name || employee.email;

  return createPortal(
    <div
      className="dialog-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="dialog availdlg"
        role="dialog"
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="dialog-header availdlg-head">
          <div className="availdlg-avatar" aria-hidden="true">
            {personInitials(label)}
          </div>
          <div className="availdlg-heading">
            <h2 id={titleId} className="dialog-title availdlg-title">
              {label}
            </h2>
            <p className="dialog-description">{t('employees.availability')}</p>
          </div>
          <button
            type="button"
            className="dialog-close"
            onClick={onClose}
            title={t('competences.close_detail')}
            aria-label={t('competences.close_detail')}
          >
            <CloseIcon />
          </button>
        </header>

        {/* `.workload` is what the calendar's own stylesheet hangs off. */}
        <div className="dialog-body availdlg-body workload">
          <WorkloadCalendar
            titleLevel={4}
            fetchEntries={fetchEntries}
            createEntry={createEntry}
            updateEntry={updateEntry}
            deleteEntry={deleteEntry}
            fetchMonthlyWish={loadWish}
            saveMonthlyWish={storeWish}
          />
        </div>
      </div>
    </div>,
    document.body
  );
};

export default EmployeeAvailabilityDialog;
