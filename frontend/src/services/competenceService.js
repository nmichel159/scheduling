import client from '../api/client';
import { fetchAllCursorPages } from '../api/pagination';

/**
 * Frontend service for the competence codebook and the bulk employee
 * competence table. All endpoints are scoped to a single ambulance and
 * require the caller to be its manager (Role 2) or an admin (Role 3+).
 */

/* ---------- ambulances managed by the current user ---------- */

/** List ambulances managed by the logged-in user. */
export async function fetchMyManagedAmbulances() {
  const { data } = await client.get('/ambulances/me/managed');
  return data;
}

/* ---------- codebook (competences of an ambulance) ---------- */

/** List competences defined for an ambulance. */
export async function fetchCompetences(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/competences`);
  return data;
}

/** Create a new competence in the ambulance codebook. */
export async function createCompetence(ambulanceId, name, description = null) {
  const { data } = await client.post(`/ambulances/${ambulanceId}/competences`, {
    name,
    description,
  });
  return data;
}

/**
 * Partially update a competence (e.g. { required_count: 3 }).
 * Returns the updated competence from the backend.
 */
export async function updateCompetence(ambulanceId, competenceId, payload) {
  const { data } = await client.put(
    `/ambulances/${ambulanceId}/competences/${competenceId}`,
    payload
  );
  return data;
}

/** Delete a competence (removes its employee assignments as well). */
export async function deleteCompetence(ambulanceId, competenceId) {
  await client.delete(`/ambulances/${ambulanceId}/competences/${competenceId}`);
}

/* ---------- employee x competence table (bulk load / bulk save) ---------- */

/** Load the full employee/competence table for an ambulance in one call. */
export async function fetchEmployeeCompetenceTable(ambulanceId) {
  return fetchAllCursorPages(
    async (afterId, limit) => {
      const { data } = await client.get(
        `/ambulances/${ambulanceId}/employees/competences`,
        { params: { after_id: afterId, limit } }
      );
      return data;
    },
    (employee) => employee.user_id
  );
}

/**
 * Persist the whole employee/competence table in one call.
 * `employees` must only contain users already assigned to the ambulance —
 * the backend rejects (400) any user_id it doesn't already know as an employee.
 */
export async function saveEmployeeCompetenceTable(ambulanceId, employees) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/employees/competences`, {
    employees,
  });
  return data;
}

/* ---------- ambulance membership ---------- */

/** Add a user as an employee of the ambulance. */
export async function addEmployeeToAmbulance(ambulanceId, userId) {
  const { data } = await client.post(`/ambulances/${ambulanceId}/employees`, {
    user_id: userId,
  });
  return data;
}

/** Remove a user as an employee of the ambulance. */
export async function removeEmployeeFromAmbulance(ambulanceId, userId) {
  await client.delete(`/ambulances/${ambulanceId}/employees/${userId}`);
}

/* ---------- user pool ---------- */

/** List all active users in the hospital (pool for adding employees). */
export async function fetchAllUsers() {
  return fetchAllCursorPages(
    async (afterId, limit) => {
      const { data } = await client.get('/users', { params: { after_id: afterId, limit } });
      return data;
    },
    (user) => user.id
  );
}

/* ---------- competence scenarios ---------- */

/**
 * The competence codebook of a workplace is shared by all of its
 * scenarios; a scenario only carries the parameters — how many people each
 * competence needs on each weekday, and how much recovery a duty costs.
 * Exactly one scenario is selected, and that is the one the schedule
 * generator and every other screen read.
 */

/** List the workplace's scenarios. The backend guarantees at least one. */
export async function fetchScenarios(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/competence-scenarios`);
  return data;
}

/** Create a scenario, optionally starting from another one's parameters. */
export async function createScenario(ambulanceId, name, copyFromScenarioId = null) {
  const { data } = await client.post(`/ambulances/${ambulanceId}/competence-scenarios`, {
    name,
    copy_from_scenario_id: copyFromScenarioId,
  });
  return data;
}

/** Rename a scenario and/or make it the selected one (e.g. { is_selected: true }). */
export async function updateScenario(ambulanceId, scenarioId, payload) {
  const { data } = await client.put(
    `/ambulances/${ambulanceId}/competence-scenarios/${scenarioId}`,
    payload
  );
  return data;
}

/** Delete a scenario. The backend refuses to remove the workplace's last one. */
export async function deleteScenario(ambulanceId, scenarioId) {
  await client.delete(`/ambulances/${ambulanceId}/competence-scenarios/${scenarioId}`);
}

/** List every competence of the workplace, valued through one scenario. */
export async function fetchScenarioCompetences(ambulanceId, scenarioId) {
  const { data } = await client.get(
    `/ambulances/${ambulanceId}/competence-scenarios/${scenarioId}/competences`
  );
  return data;
}

/**
 * Create a competence from inside a scenario. The competence itself is
 * workplace-wide, so it appears in every scenario; `weekday_requirements`
 * is what this scenario starts it at.
 */
export async function createScenarioCompetence(ambulanceId, scenarioId, payload) {
  const { data } = await client.post(
    `/ambulances/${ambulanceId}/competence-scenarios/${scenarioId}/competences`,
    payload
  );
  return data;
}

/**
 * Save the competence editor. Name and description are workplace-wide;
 * the weekly counts and recovery days only touch this scenario.
 */
export async function updateScenarioCompetence(
  ambulanceId,
  scenarioId,
  competenceId,
  payload
) {
  const { data } = await client.put(
    `/ambulances/${ambulanceId}/competence-scenarios/${scenarioId}/competences/${competenceId}`,
    payload
  );
  return data;
}

/** Delete a competence — it leaves every scenario of the workplace at once. */
export async function deleteScenarioCompetence(ambulanceId, scenarioId, competenceId) {
  await client.delete(
    `/ambulances/${ambulanceId}/competence-scenarios/${scenarioId}/competences/${competenceId}`
  );
}
