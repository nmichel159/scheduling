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
