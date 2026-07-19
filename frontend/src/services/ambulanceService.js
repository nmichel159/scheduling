import client from '../api/client';

/**
 * Frontend service wrapper for ambulance management APIs.
 * Used by managers (Role Level >= 2) to manage employee assignments.
 */

/** List ambulances managed by the given user. */
export async function fetchManagerAmbulances(userId) {
  const { data } = await client.get(`/ambulances/managers/${userId}/ambulances`);
  return data;
}

/** List ambulances the logged-in user is assigned to as an employee. */
export async function fetchMyAssignedAmbulances() {
  const { data } = await client.get('/ambulances/me/assigned');
  return data;
}

/** List employees assigned to an ambulance (manager-owned only). */
export async function fetchEmployees(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/employees`);
  return data;
}

/** Assign a user to an ambulance. */
export async function addEmployee(ambulanceId, userId) {
  const { data } = await client.post(`/ambulances/${ambulanceId}/employees`, {
    user_id: userId,
  });
  return data;
}

/** Remove a user from an ambulance. */
export async function removeEmployee(ambulanceId, userId) {
  await client.delete(`/ambulances/${ambulanceId}/employees/${userId}`);
}

/** List all active users (manager role required). */
export async function fetchUsers() {
  const { data } = await client.get('/users/');
  return data;
}

/** List role IDs assigned to the logged-in user. */
export async function fetchUserRoles(userId) {
  const { data } = await client.get(`/users/${userId}/roles`);
  return data;
}

/* ---------- admin (Role Level >= 3): full ambulance CRUD + manager assignment ---------- */

/** List all active ambulances. */
export async function fetchAllAmbulances() {
  const { data } = await client.get('/ambulances');
  return data;
}

/** Create a new ambulance. */
export async function createAmbulance({ name, description = null, isurgent = false }) {
  const { data } = await client.post('/ambulances', { name, description, isurgent });
  return data;
}

/** Update an existing ambulance. */
export async function updateAmbulance(ambulanceId, { name, description, isurgent }) {
  const { data } = await client.put(`/ambulances/${ambulanceId}`, { name, description, isurgent });
  return data;
}

/** Soft-delete an ambulance. */
export async function deleteAmbulance(ambulanceId) {
  await client.delete(`/ambulances/${ambulanceId}`);
}

/** Assign a manager to an ambulance. */
export async function assignManagerToAmbulance(ambulanceId, userId) {
  const { data } = await client.put(`/ambulances/${ambulanceId}/manager/${userId}`);
  return data;
}

/** Remove the assigned manager from an ambulance. */
export async function removeManagerFromAmbulance(ambulanceId) {
  await client.delete(`/ambulances/${ambulanceId}/manager`);
}
