import client from '../api/client';

/**
 * Frontend service for mailing one workplace's monthly schedule out.
 *
 * The clinic does not log in — it reads the finished month in a mailbox —
 * so every workplace keeps its own list of addresses, and every send is
 * recorded, the failed ones too.
 *
 * A refusal comes back as HTTP 409 with `detail.code`: `empty_schedule`,
 * `not_approved` or `no_recipients`. `refusalCode` below pulls it out so the
 * screen can name the reason instead of showing one generic failure.
 */

export async function fetchMailRecipients(ambulanceId) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/mail-recipients`);
  return data;
}

export async function addMailRecipient(ambulanceId, email, label = null) {
  const { data } = await client.post(`/ambulances/${ambulanceId}/mail-recipients`, {
    email,
    label,
  });
  return data;
}

export async function deleteMailRecipient(ambulanceId, recipientId) {
  await client.delete(`/ambulances/${ambulanceId}/mail-recipients/${recipientId}`);
}

/** What would be sent for a month, rendered without sending it. */
export async function fetchSchedulePreview(ambulanceId, month, year, note = null) {
  const { data } = await client.get(
    `/ambulances/${ambulanceId}/schedule/mail-preview`,
    { params: { month, year, ...(note ? { note } : {}) } }
  );
  return data;
}

/** Send the month. `recipientIds` of null mails every address. */
export async function sendScheduleMail(
  ambulanceId,
  month,
  year,
  { recipientIds = null, note = null } = {}
) {
  const { data } = await client.post(
    `/ambulances/${ambulanceId}/schedule/mail`,
    { recipient_ids: recipientIds, note },
    { params: { month, year } }
  );
  return data;
}

export async function fetchMailLog(ambulanceId, limit = 20) {
  const { data } = await client.get(`/ambulances/${ambulanceId}/schedule/mail-log`, {
    params: { limit },
  });
  return data;
}

/** The machine-readable reason a 409 refused a preview or a send. */
export function refusalCode(error) {
  const detail = error?.response?.data?.detail;
  return typeof detail === 'object' && detail ? detail.code || null : null;
}
