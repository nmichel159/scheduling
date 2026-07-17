import client from '../api/client';

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

/** Delete a competence (removes its employee assignments as well). */
export async function deleteCompetence(ambulanceId, competenceId) {
  await client.delete(`/ambulances/${ambulanceId}/competences/${competenceId}`);
}

/* ---------- employee x competence table (bulk load / bulk save) ---------- */

/** Load the full employee/competence table for an ambulance in one call. */
export async function fetchEmployeeCompetenceTable(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/employees/competences`);
  return data;
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
  const { data } = await client.get('/users/');
  return data;
}
