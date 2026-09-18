import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import WorkloadCalendar from '../components/WorkloadCalendar';
import { useWorkplace } from '../hooks/workplaceContext';
import { fetchEmployees } from '../services/ambulanceService';
import {
  fetchEmployeeUnavailabilities,
  createEmployeeUnavailability,
  updateEmployeeUnavailability,
  deleteEmployeeUnavailability,
} from '../services/unavailabilityService';
import './ManagerWorkloadView.css';

/** Manager view for editing one employee's restriction calendar. */
const ManagerWorkloadView = () => {
  const { t } = useTranslation();
  // Which workplace is being managed comes from the header switcher.
  const {
    workplaces: ambulances,
    activeId: selectedAmbulanceId,
    active: selectedAmbulance,
    loading,
    error: workplacesError,
  } = useWorkplace();

  const [employees, setEmployees] = useState([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(null);
  // The workplace `employees` actually describes. Switching workplaces would
  // otherwise leave one render pairing the new workplace with the previous
  // employee, and WorkloadCalendar would ask for a combination that isn't one.
  const [loadedAmbulanceId, setLoadedAmbulanceId] = useState(null);
  const [employeesLoading, setEmployeesLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (selectedAmbulanceId == null) {
      setEmployees([]);
      setSelectedEmployeeId(null);
      setLoadedAmbulanceId(null);
      return undefined;
    }

    let cancelled = false;
    (async () => {
      setEmployeesLoading(true);
      setError(null);
      setEmployees([]);
      setSelectedEmployeeId(null);
      try {
        const list = await fetchEmployees(selectedAmbulanceId);
        if (cancelled) return;
        setEmployees(list);
        setSelectedEmployeeId(list[0]?.user_id ?? null);
        setLoadedAmbulanceId(selectedAmbulanceId);
      } catch {
        if (!cancelled) setError(t('manager_workload.load_employees_error'));
      } finally {
        if (!cancelled) setEmployeesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedAmbulanceId, t]);

  const selectedEmployee = useMemo(
    () => employees.find((item) => item.user_id === selectedEmployeeId) || null,
    [employees, selectedEmployeeId]
  );

  const fetchEntries = useCallback(
    (dateFrom, dateTo) =>
      fetchEmployeeUnavailabilities(
        selectedAmbulanceId,
        selectedEmployeeId,
        dateFrom,
        dateTo
      ),
    [selectedAmbulanceId, selectedEmployeeId]
  );
  const createEntry = useCallback(
    (dateAbsent, reason) =>
      createEmployeeUnavailability(
        selectedAmbulanceId,
        selectedEmployeeId,
        dateAbsent,
        reason
      ),
    [selectedAmbulanceId, selectedEmployeeId]
  );
  const updateEntry = useCallback(
    (id, reason) =>
      updateEmployeeUnavailability(
        selectedAmbulanceId,
        selectedEmployeeId,
        id,
        reason
      ),
    [selectedAmbulanceId, selectedEmployeeId]
  );
  const deleteEntry = useCallback(
    (id) => deleteEmployeeUnavailability(selectedAmbulanceId, selectedEmployeeId, id),
    [selectedAmbulanceId, selectedEmployeeId]
  );

  if (loading) {
    return <div className="manager-workload"><p>{t('manager_workload.loading')}</p></div>;
  }

  if (ambulances.length === 0) {
    return (
      <div className="manager-workload">
        <h1 className="manager-workload-title">{t('manager_workload.title')}</h1>
        <div className="manager-workload-banner">
          {workplacesError
            ? t('manager_workload.load_ambulances_error')
            : t('manager_workload.no_ambulances')}
        </div>
      </div>
    );
  }

  // The workplace list is now the header switcher's job; the page is always
  // the single-column detail of whatever it points at.
  const staleEmployees = loadedAmbulanceId !== selectedAmbulanceId;

  return (
    <div className="manager-workload">
      <h1 className="manager-workload-title">{t('manager_workload.title')}</h1>
      <p className="manager-workload-subtitle">{t('manager_workload.subtitle')}</p>

      {error && <div className="manager-workload-banner is-error">{error}</div>}

      <div className="manager-workload-layout is-single">
        <section className="manager-workload-detail">
          <header className="manager-workload-detail-head">
            <div>
              <h2>{selectedAmbulance?.name}</h2>
              {selectedAmbulance?.description && <p>{selectedAmbulance.description}</p>}
            </div>
            <label className="manager-workload-employee-select">
              <span>{t('manager_workload.employee')}</span>
              <select
                value={selectedEmployeeId ?? ''}
                onChange={(event) => setSelectedEmployeeId(Number(event.target.value))}
                disabled={employeesLoading || staleEmployees || employees.length === 0}
              >
                {employees.length === 0 && (
                  <option value="">{t('manager_workload.pick_employee')}</option>
                )}
                {employees.map((employee) => (
                  <option key={employee.user_id} value={employee.user_id}>
                    {employee.full_name || employee.email}
                  </option>
                ))}
              </select>
            </label>
          </header>

          {(employeesLoading || staleEmployees) && (
            <p>{t('manager_workload.loading_employees')}</p>
          )}
          {!employeesLoading && !staleEmployees && employees.length === 0 && (
            <div className="manager-workload-empty">{t('manager_workload.no_employees')}</div>
          )}
          {!employeesLoading && !staleEmployees && selectedEmployee && (
            <WorkloadCalendar
              key={`${selectedAmbulanceId}:${selectedEmployeeId}`}
              title={selectedEmployee.full_name || selectedEmployee.email}
              titleLevel={3}
              fetchEntries={fetchEntries}
              createEntry={createEntry}
              updateEntry={updateEntry}
              deleteEntry={deleteEntry}
            />
          )}
        </section>
      </div>
    </div>
  );
};

export default ManagerWorkloadView;