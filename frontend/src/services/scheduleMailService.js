import client from '../api/client';

/**
 * Frontend service for asking employees to fill their schedule in.
 *
 * The message goes out from the application's own mailbox with the
 * scheduler's name and their address as Reply-To: the application has no
 * access to anybody's personal mailbox, so a reply reaching the scheduler
 * is the closest thing to sending it as them.
 */

/** The signed-in scheduler's workplaces, each with its employees. */
export async function fetchFillRequestGroups() {
  const { data } = await client.get('/ambulances/mail/fill-request-groups');
  return data;
}

/** The default wording, which the scheduler edits before sending. */
export async function fetchFillRequestTemplate() {
  const { data } = await client.get('/ambulances/mail/fill-request-template');
  return data;
}

/** Mail the chosen employees the request to fill their schedule in. */
export async function sendFillRequest(userIds, subject, body) {
  const { data } = await client.post('/ambulances/mail/fill-request', {
    user_ids: userIds,
    subject,
    body,
  });
  return data;
}

/** The machine-readable reason a 409 refused a send. */
export function refusalCode(error) {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'object' && detail ? detail.code || null : null;
}
