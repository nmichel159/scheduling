import client from '../api/client';
import { fetchAllCursorPages } from '../api/pagination';

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
  return fetchAllCursorPages(
    async (afterId, limit) => {
      const { data } = await client.get('/users/role-assignments', {
        params: { after_id: afterId, limit },
      });
      return data;
    },
    (user) => user.id
  );
}


export async function updateUserRoles(userId, roleIds) {
  const { data } = await client.put(`/users/${userId}/roles`, { role_ids: roleIds });
  return data;
}
