import client from '../api/client';

/** Zoznam rolí prihláseného usera: [{ name: 'LEADER', index: 2 }, ...] */
export async function fetchMyRoles() {
  const { data } = await client.get('/roles/me');
  return data;
}


export async function fetchAllRoles() {
  const { data } = await client.get('/roles');
  return data;
}


export async function fetchRoleAssignments() {
  const { data } = await client.get('/users/role-assignments');
  return data;
}


export async function updateUserRoles(userId, roleIds) {
  const { data } = await client.put(`/users/${userId}/roles`, { role_ids: roleIds });
  return data;
}
