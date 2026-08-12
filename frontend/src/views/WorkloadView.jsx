import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import WorkloadCalendar from '../components/WorkloadCalendar';
import {
  fetchUnavailabilities,
  createUnavailability,
  updateUnavailability,
  deleteUnavailability,
} from '../services/unavailabilityService';
import './WorkloadView.css';

/** The authenticated employee's own restriction calendar. */
const WorkloadView = () => {
  const { t } = useTranslation();
  const fetchEntries = useCallback(
    (dateFrom, dateTo) => fetchUnavailabilities(dateFrom, dateTo),
    []
  );
  const createEntry = useCallback(
    (dateAbsent, reason) => createUnavailability(dateAbsent, reason),
    []
  );
  const updateEntry = useCallback((id, reason) => updateUnavailability(id, reason), []);
  const deleteEntry = useCallback((id) => deleteUnavailability(id), []);

  return (
    <div className="workload">
      <WorkloadCalendar
        title={t('workload.title')}
        fetchEntries={fetchEntries}
        createEntry={createEntry}
        updateEntry={updateEntry}
        deleteEntry={deleteEntry}
      />
    </div>
  );
};

export default WorkloadView;
