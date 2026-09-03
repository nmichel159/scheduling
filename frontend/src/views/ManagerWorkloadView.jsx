import { useState, useEffect, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import WorkloadCalendar from '../components/WorkloadCalendar';
import { fetchMyManagedAmbulances } from '../services/competenceService';
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
  const [ambulances, setAmbulances] = useState([]);
  const [selectedAmbulanceId, setSelectedAmbulanceId] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [employeesLoading, setEmployeesLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const list = await fetchMyManagedAmbulances();
        if (cancelled) return;
        setAmbulances(list);
        setSelectedAmbulanceId(list[0]?.id ?? null);
      } catch {
        if (!cancelled) setError(t('manager_workload.load_ambulances_error'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    if (selectedAmbulanceId == null) {
      setEmployees([]);
      setSelectedEmployeeId(null);
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

  const selectedAmbulance = useMemo(
    () => ambulances.find((item) => item.id === selectedAmbulanceId) || null,
    [ambulances, selectedAmbulanceId]
  );
  const selectedEmployee = useMemo(
    () => employees.find((item) => item.user_id === selectedEmployeeId) || null,
    [employees, selectedEmployeeId]
  );

  const selectAmbulance = useCallback((ambulanceId) => {
    if (ambulanceId === selectedAmbulanceId) return;
    // Clear the old employee in the click event itself. Waiting for the
    // selected-ambulance effect leaves one render where WorkloadCalendar can
    // request the previous employee under the newly selected ambulance.
    setSelectedEmployeeId(null);
    setEmployees([]);
    setSelectedAmbulanceId(ambulanceId);
  }, [selectedAmbulanceId]);

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
          {error || t('manager_workload.no_ambulances')}
        </div>
      </div>
    );
  }

  const showAmbulanceList = ambulances.length > 1;

  return (
    <div className="manager-workload">
      <h1 className="manager-workload-title">{t('manager_workload.title')}</h1>
      <p className="manager-workload-subtitle">{t('manager_workload.subtitle')}</p>

      {error && <div className="manager-workload-banner is-error">{error}</div>}

      <div className={`manager-workload-layout ${showAmbulanceList ? '' : 'is-single'}`}>
        {showAmbulanceList && (
          <nav
            className="manager-workload-ambulances"
            aria-label={t('manager_workload.ambulances')}
          >
            {ambulances.map((ambulance) => (
              <button
                type="button"
                key={ambulance.id}
                className={`manager-workload-ambulance ${
                  ambulance.id === selectedAmbulanceId ? 'is-selected' : ''
                }`}
                onClick={() => selectAmbulance(ambulance.id)}
              >
                <span className="manager-workload-ambulance-name">{ambulance.name}</span>
                {ambulance.description && (
                  <span className="manager-workload-ambulance-description">
                    {ambulance.description}
                  </span>
                )}
              </button>
            ))}
          </nav>
        )}

        <section className="manager-workload-detail">
          <header className="manager-workload-detail-head">
            <div>
              <h2>{selectedAmbulance?.name}</h2>
              {!showAmbulanceList && selectedAmbulance?.description && (
                <p>{selectedAmbulance.description}</p>
              )}
            </div>
            <label className="manager-workload-employee-select">
              <span>{t('manager_workload.employee')}</span>
              <select
                value={selectedEmployeeId ?? ''}
                onChange={(event) => setSelectedEmployeeId(Number(event.target.value))}
                disabled={employeesLoading || employees.length === 0}
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

          {employeesLoading && <p>{t('manager_workload.loading_employees')}</p>}
          {!employeesLoading && employees.length === 0 && (
            <div className="manager-workload-empty">{t('manager_workload.no_employees')}</div>
          )}
          {!employeesLoading && selectedEmployee && (
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