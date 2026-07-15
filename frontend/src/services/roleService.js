import client from '../api/client';

/** Zoznam rolí prihláseného usera: [{ name: 'LEADER', index: 2 }, ...] */
export async function fetchMyRoles() {
  const { data } = await client.get('/roles/me');
  return data;
}