import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ConfirmDialog from '../components/ConfirmDialog';
import {
  fetchFillRequestGroups,
  fetchFillRequestTemplate,
  refusalCode,
  sendFillRequest,
} from '../services/scheduleMailService';
import './ScheduleMailView.css';

/** A tick identifies a person inside one workplace, not a person alone. */
const memberKey = (group, employee) =>
  `${group.ambulance_id}:${employee.user_id}`;

/**
 * Asking the employees to fill their schedule in.
 *
 * The scheduler thinks in workplaces, not in addresses, so the people are
 * picked through the groups they already belong to — one collapsible block
 * per workplace, with the whole group tickable at once.
 *
 * A tick belongs to a workplace, not to a person: the same people staff
 * several workplaces, and unticking one of them must not quietly drop
 * somebody who is still ticked in another. So the selection is keyed by
 * workplace and person together, and the send is the union of the
 * addresses -- one message per person, however many groups they were
 * ticked in.
 *
 * The message itself is editable. A default is offered with the sign-in
 * link already in it, but a send that cannot be taken back should show
 * exactly what goes out, and the wording changes from month to month.
 */
const ScheduleMailView = () => {
  const { t } = useTranslation();

  const [groups, setGroups] = useState([]);
  const [openGroups, setOpenGroups] = useState([]);
  const [selectedKeys, setSelectedKeys] = useState([]);
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sendAsked, setSendAsked] = useState(false);
  const [toast, setToast] = useState(null);

  const notify = (message) => {
    setToast(message);
    setTimeout(() => setToast(null), 3200);
  };

  const load = useCallback(async () => {
    const [groupList, template] = await Promise.all([
      fetchFillRequestGroups(),
      fetchFillRequestTemplate(),
    ]);
    setGroups(groupList);
    setSubject(template.subject);
    setBody(template.body);
  }, []);

  useEffect(() => {
    load()
      .catch(() => setLoadError(true))
      .finally(() => setLoaded(true));
  }, [load]);

  const toggleGroupOpen = (ambulanceId) => {
    setOpenGroups((current) =>
      current.includes(ambulanceId)
        ? current.filter((item) => item !== ambulanceId)
        : [...current, ambulanceId]
    );
  };

  const toggleMember = (key) => {
    setSelectedKeys((current) =>
      current.includes(key)
        ? current.filter((item) => item !== key)
        : [...current, key]
    );
  };

  const groupState = (group) => {
    const keys = group.employees.map((item) => memberKey(group, item));
    const picked = keys.filter((key) => selectedKeys.includes(key));
    return { keys, all: keys.length > 0 && picked.length === keys.length };
  };

  const toggleGroup = (group) => {
    const { keys, all } = groupState(group);
    setSelectedKeys((current) =>
      all
        ? current.filter((key) => !keys.includes(key))
        : [...current, ...keys.filter((key) => !current.includes(key))]
    );
  };

  /* One tick anywhere is enough: a person ticked in any workplace gets the
     message once, and the address is what makes two rows the same person. */
  const selectedPeople = useMemo(() => {
    const seen = new Map();
    groups.forEach((group) => {
      group.employees.forEach((employee) => {
        if (selectedKeys.includes(memberKey(group, employee))) {
          seen.set(employee.email, {
            address: employee.email,
            name: employee.full_name || employee.email,
            userId: employee.user_id,
          });
        }
      });
    });
    return [...seen.values()];
  }, [groups, selectedKeys]);

  const handleSend = async () => {
    setSendAsked(false);
    setBusy(true);
    try {
      await sendFillRequest(
        selectedPeople.map((person) => person.userId),
        subject.trim(),
        body.trim()
      );
      setSelectedKeys([]);
      notify(t('schedule_mail.sent'));
    } catch (error) {
      notify(
        refusalCode(error) === 'no_recipients'
          ? t('schedule_mail.no_selection')
          : error?.response?.status === 503
            ? t('schedule_mail.not_configured')
            : t('schedule_mail.send_failed')
      );
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) {
    return <div className="smail"><p>{t('departments.loading')}</p></div>;
  }

  const canSend =
    !busy &&
    selectedPeople.length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0;

  return (
    <div className="smail">
      <h1 className="smail-title">{t('schedule_mail.title')}</h1>

      {loadError && <div className="smail-banner">{t('schedule_mail.load_error')}</div>}

      <section className="smail-card">
        <h2>{t('schedule_mail.recipients')}</h2>
        {groups.length === 0 ? (
          <p className="smail-note">{t('schedule_mail.no_groups')}</p>
        ) : (
          <ul className="smail-groups">
            {groups.map((group) => {
              const { all } = groupState(group);
              const open = openGroups.includes(group.ambulance_id);
              return (
                <li key={group.ambulance_id} className="smail-group">
                  <div className="smail-group-head">
                    <label className="smail-check">
                      <input
                        type="checkbox"
                        checked={all}
                        onChange={() => toggleGroup(group)}
                      />
                      <span className="smail-email">{group.ambulance_name}</span>
                    </label>
                    <button
                      type="button"
                      className="smail-btn"
                      aria-expanded={open}
                      onClick={() => toggleGroupOpen(group.ambulance_id)}
                    >
                      {open ? '−' : '+'}
                    </button>
                  </div>
                  {open && (
                    <ul className="smail-list smail-group-list">
                      {group.employees.map((employee) => (
                        <li key={employee.user_id}>
                          <label className="smail-check">
                            <input
                              type="checkbox"
                              checked={selectedKeys.includes(
                                memberKey(group, employee)
                              )}
                              onChange={() =>
                                toggleMember(memberKey(group, employee))
                              }
                            />
                            <span className="smail-email">
                              {employee.full_name || employee.email}
                            </span>
                            <em className="smail-label">{employee.email}</em>
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {selectedPeople.length > 0 && (
          <p className="smail-note smail-selected">
            {selectedPeople.map((person) => person.name).join(', ')}
          </p>
        )}
      </section>

      <section className="smail-card">
        <h2>{t('schedule_mail.message')}</h2>
        <input
          type="text"
          className="smail-input smail-subject-input"
          aria-label={t('schedule_mail.subject')}
          maxLength={300}
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
        />
        <textarea
          className="smail-textarea"
          aria-label={t('schedule_mail.message')}
          rows={8}
          maxLength={5000}
          value={body}
          onChange={(event) => setBody(event.target.value)}
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

      <ConfirmDialog
        open={sendAsked}
        message={t('schedule_mail.send_confirm')}
        details={selectedPeople.map((person) => person.address).join(', ')}
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
