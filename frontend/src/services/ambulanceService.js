import client from '../api/client';
import { fetchAllCursorPages } from '../api/pagination';

/**
 * Frontend service wrapper for ambulance management APIs.
 * Used by managers (Role Level >= 2) to manage employee assignments.
 */

/** List ambulances managed by the logged-in user. */
export async function fetchManagerAmbulances() {
  const { data } = await client.get('/ambulances/me/managed');
  return data;
}

/** List ambulances the logged-in user is assigned to as an employee. */
export async function fetchMyAssignedAmbulances() {
  const { data } = await client.get('/ambulances/me/assigned');
  return data;
}

/** List employees assigned to an ambulance (manager-owned only). */
export async function fetchEmployees(ambulanceId) {
  return fetchAllCursorPages(
    async (afterId, limit) => {
      const { data } = await client.get(`/ambulances/${ambulanceId}/employees`, {
        params: { after_id: afterId, limit },
      });
      return data;
    },
    (employee) => employee.user_id
  );
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
  return fetchAllCursorPages(
    async (afterId, limit) => {
      const { data } = await client.get('/users', { params: { after_id: afterId, limit } });
      return data;
    },
    (user) => user.id
  );
}

/** List active users holding a specific role (e.g. 2 = LEADER, 3 = AMBULANCE_OVERSEER). */
export async function fetchUsersByRole(roleId) {
  return fetchAllCursorPages(
    async (afterId, limit) => {
      const { data } = await client.get('/users/by-role', {
        params: { role_id: roleId, after_id: afterId, limit },
      });
      return data;
    },
    (user) => user.id
  );
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

/**
 * Create a new ambulance.
 *
 * `managerId` je nepovinné — backend (POST /ambulances) prijíma `manager_id`
 * priamo v tele požiadavky a overí ho cez _validate_manager(), takže ambulancia
 * aj priradenie manažéra vzniknú v jednej atomickej operácii.
 */
export async function createAmbulance({
  name,
  description = null,
  isurgent = false,
  managerId = null,
}) {
  const { data } = await client.post('/ambulances', {
    name,
    description,
    isurgent,
    manager_id: managerId,
  });
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
