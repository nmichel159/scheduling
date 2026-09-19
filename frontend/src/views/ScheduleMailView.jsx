import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ConfirmDialog from '../components/ConfirmDialog';
import { useWorkplace } from '../hooks/workplaceContext';
import {
  addMailRecipient,
  deleteMailRecipient,
  fetchMailLog,
  fetchMailRecipients,
  fetchSchedulePreview,
  refusalCode,
  sendScheduleMail,
} from '../services/scheduleMailService';
import './ScheduleMailView.css';

const MONTHS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];

/** How far either side of this year the year picker reaches. */
const YEAR_SPAN = 2;

/**
 * Mailing one workplace's approved monthly schedule to its clinic.
 *
 * The clinic is not a user of this system: nobody there logs in, and the
 * people who need the finished month — the head of the clinic, the ward
 * secretary — read it in a mailbox. So the screen carries three things in
 * one place: the addresses this workplace mails to, the month as it would
 * arrive, and the record of what has already left, failures included.
 *
 * The preview is not decoration. A send cannot be taken back, and the
 * backend refuses an unapproved or empty month; showing exactly what would
 * go out — and, when it refuses, why — is what makes the send button safe
 * to press.
 */
const ScheduleMailView = () => {
  const { t } = useTranslation();
  const {
    workplaces,
    activeId,
    active,
    loading: workplacesLoading,
    error: workplacesError,
    forbidden,
  } = useWorkplace();

  const today = useMemo(() => new Date(), []);
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [year, setYear] = useState(today.getFullYear());

  const [recipients, setRecipients] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [preview, setPreview] = useState(null);
  const [previewProblem, setPreviewProblem] = useState(null);
  const [log, setLog] = useState([]);

  const [email, setEmail] = useState('');
  const [label, setLabel] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [sendAsked, setSendAsked] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (message) => {
    setToast(message);
    setTimeout(() => setToast(null), 3200);
  };

  const years = useMemo(() => {
    const current = new Date().getFullYear();
    return Array.from(
      { length: YEAR_SPAN * 2 + 1 },
      (_unused, offset) => current - YEAR_SPAN + offset
    );
  }, []);

  const loadRecipients = useCallback(async () => {
    if (activeId == null) return;
    const list = await fetchMailRecipients(activeId);
    setRecipients(list);
    setSelectedIds(list.map((item) => item.id));
  }, [activeId]);

  const loadLog = useCallback(async () => {
    if (activeId == null) return;
    setLog(await fetchMailLog(activeId));
  }, [activeId]);

  const loadPreview = useCallback(async () => {
    if (activeId == null) return;
    try {
      setPreview(await fetchSchedulePreview(activeId, month, year));
      setPreviewProblem(null);
    } catch (error) {
      setPreview(null);
      setPreviewProblem(refusalCode(error) || 'load_error');
    }
  }, [activeId, month, year]);

  useEffect(() => {
    if (activeId == null) {
      setRecipients([]);
      setSelectedIds([]);
      setPreview(null);
      setLog([]);
      return;
    }
    loadRecipients().catch(() => notify(t('schedule_mail.load_error')));
    loadLog().catch(() => setLog([]));
  }, [activeId, loadRecipients, loadLog, t]);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  const toggleRecipient = (id) => {
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id]
    );
  };

  const handleAdd = async (event) => {
    event.preventDefault();
    if (busy || !email.trim()) return;
    setBusy(true);
    try {
      await addMailRecipient(activeId, email.trim(), label.trim() || null);
      setEmail('');
      setLabel('');
      await loadRecipients();
    } catch (error) {
      notify(
        error?.response?.status === 409
          ? t('schedule_mail.duplicate_error')
          : t('schedule_mail.invalid_email')
      );
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (recipientId) => {
    if (busy) return;
    setBusy(true);
    try {
      await deleteMailRecipient(activeId, recipientId);
      await loadRecipients();
    } catch {
      notify(t('schedule_mail.save_error'));
    } finally {
      setBusy(false);
    }
  };

  const handleSend = async () => {
    setSendAsked(false);
    setBusy(true);
    try {
      const dispatch = await sendScheduleMail(activeId, month, year, {
        recipientIds: selectedIds,
        note: note.trim() || null,
      });
      await loadLog();
      if (dispatch.status === 'failed') {
        notify(t('schedule_mail.send_failed'));
      } else {
        setNote('');
        notify(t('schedule_mail.sent'));
      }
    } catch (error) {
      const code = refusalCode(error);
      notify(
        code
          ? t(`schedule_mail.refusal.${code}`)
          : error?.response?.status === 503
            ? t('schedule_mail.not_configured')
            : t('schedule_mail.send_failed')
      );
    } finally {
      setBusy(false);
    }
  };

  if (workplacesLoading) {
    return <div className="smail"><p>{t('departments.loading')}</p></div>;
  }

  if (forbidden || workplaces.length === 0) {
    return (
      <div className="smail">
        <h1 className="smail-title">{t('schedule_mail.title')}</h1>
        <div className="smail-banner">
          {forbidden ? t('departments.forbidden') : t('departments.no_ambulances')}
        </div>
      </div>
    );
  }

  const canSend = Boolean(preview) && selectedIds.length > 0 && !busy;

  return (
    <div className="smail">
      <h1 className="smail-title">{t('schedule_mail.title')}</h1>

      {workplacesError && (
        <div className="smail-banner">{t('schedule_mail.load_error')}</div>
      )}

      <div className="smail-bar">
        <select
          className="smail-select"
          aria-label={t('schedule_mail.month')}
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
        >
          {MONTHS.map((index) => (
            <option key={index} value={index + 1}>
              {t(`special_days.months.${index}`)}
            </option>
          ))}
        </select>
        <select
          className="smail-select"
          aria-label={t('schedule_mail.year')}
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
        >
          {years.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
        <span className="smail-workplace">{active?.name}</span>
      </div>

      <section className="smail-card">
        <h2>{t('schedule_mail.recipients')}</h2>
        {recipients.length === 0 ? (
          <p className="smail-note">{t('schedule_mail.no_recipients')}</p>
        ) : (
          <ul className="smail-list">
            {recipients.map((item) => (
              <li key={item.id}>
                <label className="smail-check">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(item.id)}
                    onChange={() => toggleRecipient(item.id)}
                  />
                  <span className="smail-email">{item.email}</span>
                  {item.label && <em className="smail-label">{item.label}</em>}
                </label>
                <button
                  type="button"
                  className="smail-btn"
                  disabled={busy}
                  onClick={() => handleDelete(item.id)}
                >
                  {t('schedule_mail.remove')}
                </button>
              </li>
            ))}
          </ul>
        )}

        <form className="smail-add" onSubmit={handleAdd}>
          <input
            type="email"
            className="smail-input"
            placeholder={t('schedule_mail.email')}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="text"
            className="smail-input"
            placeholder={t('schedule_mail.label')}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button type="submit" className="smail-btn" disabled={busy || !email.trim()}>
            {t('schedule_mail.add')}
          </button>
        </form>
      </section>

      <section className="smail-card">
        <h2>{t('schedule_mail.preview')}</h2>
        {previewProblem ? (
          <p className="smail-note">
            {t(
              previewProblem === 'load_error'
                ? 'schedule_mail.load_error'
                : `schedule_mail.refusal.${previewProblem}`
            )}
          </p>
        ) : (
          preview && (
            <>
              <p className="smail-subject">{preview.subject}</p>
              <p className="smail-note">
                {t('schedule_mail.entry_count', { count: preview.entry_count })}
              </p>
              <pre className="smail-body">{preview.text_body}</pre>
            </>
          )
        )}

        <textarea
          className="smail-textarea"
          rows={3}
          maxLength={2000}
          placeholder={t('schedule_mail.note')}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />

        <button
          type="button"
          className="smail-btn smail-btn-primary"
          disabled={!canSend}
          onClick={() => setSendAsked(true)}
        >
          {t('schedule_mail.send')}
        </button>
      </section>

      <section className="smail-card">
        <h2>{t('schedule_mail.log')}</h2>
        {log.length === 0 ? (
          <p className="smail-note">{t('schedule_mail.log_empty')}</p>
        ) : (
          <table className="smail-table">
            <thead>
              <tr>
                <th>{t('schedule_mail.sent_at')}</th>
                <th>{t('schedule_mail.period')}</th>
                <th>{t('schedule_mail.recipients')}</th>
                <th>{t('schedule_mail.status')}</th>
              </tr>
            </thead>
            <tbody>
              {log.map((item) => (
                <tr key={item.id}>
                  <td>
                    {item.created_at
                      ? new Date(item.created_at).toLocaleString()
                      : ''}
                  </td>
                  <td>{`${String(item.month).padStart(2, '0')}/${item.year}`}</td>
                  <td className="smail-recipients">{item.recipients}</td>
                  <td>
                    <span className={`smail-status is-${item.status}`}>
                      {t(`schedule_mail.statuses.${item.status}`)}
                    </span>
                    {item.error && <em className="smail-error">{item.error}</em>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <ConfirmDialog
        open={sendAsked}
        message={t('schedule_mail.send_confirm')}
        details={recipients
          .filter((item) => selectedIds.includes(item.id))
          .map((item) => item.email)
          .join(', ')}
        confirmLabel={t('schedule_mail.send')}
        cancelLabel={t('sidebar.cancel')}
        onConfirm={handleSend}
        onCancel={() => setSendAsked(false)}
      />

      {toast && <div className="smail-toast" role="status">{toast}</div>}
    </div>
  );
};

export default ScheduleMailView;
