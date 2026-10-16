import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import ConfirmDialog from '../components/ConfirmDialog';
import Toast from '../components/Toast';
import { ChevronDownIcon, MailIcon } from '../components/NavIcons';
import { useToast } from '../hooks/useToast';
import {
  fetchFillRequestGroups,
  fetchFillRequestTemplate,
  refusalCode,
  sendFillRequest,
} from '../services/scheduleMailService';
import PageSkeleton from '../components/Skeleton';
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
 *
 * A successful send is confirmed by a passing toast; a failed one stays on
 * the page beside the button until the next attempt, because "mail is not
 * configured" is not something to read in the three seconds a toast lasts.
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
  const [sendError, setSendError] = useState(null);
  // The shared hook: it clears its timer on unmount, and a newer message
  // restarts the clock instead of being cut short by the older one's timer.
  const [toast, notify] = useToast(3200);

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
    return {
      keys,
      picked: picked.length,
      all: keys.length > 0 && picked.length === keys.length,
    };
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
    setSendError(null);
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
      setSendError(
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
    return (
      <PageSkeleton
        className="page smail"
        title={t('schedule_mail.title')}
        label={t('departments.loading')}
      />
    );
  }

  const canSend =
    !busy &&
    selectedPeople.length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0;

  const membersLabel = (open) =>
    open ? t('schedule_mail.hide_members') : t('schedule_mail.show_members');

  return (
    <div className="page smail">
      <header className="page-header">
        <div>
          <h1 className="page-title">{t('schedule_mail.title')}</h1>
        </div>
      </header>

      {loadError && (
        <div className="alert alert-danger smail-alert" role="alert">
          {t('schedule_mail.load_error')}
        </div>
      )}

      <div className="smail-layout">
        <section className="card smail-recipients" aria-labelledby="smail-recipients-title">
          <div className="card-header">
            <h2 id="smail-recipients-title" className="card-title">
              {t('schedule_mail.recipients')}
            </h2>
            <span
              className={`badge ${selectedPeople.length > 0 ? 'badge-primary' : ''}`}
              aria-live="polite"
            >
              {t('schedule_mail.selected_count', { people: selectedPeople.length })}
            </span>
          </div>

          {groups.length === 0 ? (
            <p className="empty-state smail-empty">{t('schedule_mail.no_groups')}</p>
          ) : (
            <ul className="smail-groups">
              {groups.map((group) => {
                const { all, picked } = groupState(group);
                const open = openGroups.includes(group.ambulance_id);
                const listId = `smail-group-${group.ambulance_id}`;
                return (
                  <li key={group.ambulance_id} className="smail-group">
                    <div className="smail-group-head">
                      <label className="smail-check smail-group-check">
                        <input
                          type="checkbox"
                          checked={all}
                          /* Part of the group ticked: the box says so instead
                             of looking simply empty. */
                          ref={(element) => {
                            if (element) element.indeterminate = picked > 0 && !all;
                          }}
                          disabled={group.employees.length === 0}
                          onChange={() => toggleGroup(group)}
                        />
                        <span className="smail-group-name">{group.ambulance_name}</span>
                      </label>
                      <span className="smail-group-count">
                        {picked}/{group.employees.length}
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-icon btn-sm smail-group-toggle"
                        aria-expanded={open}
                        aria-controls={listId}
                        aria-label={`${group.ambulance_name}: ${membersLabel(open)}`}
                        title={membersLabel(open)}
                        onClick={() => toggleGroupOpen(group.ambulance_id)}
                      >
                        <ChevronDownIcon className={open ? 'is-open' : ''} />
                      </button>
                    </div>
                    {open && (
                      <ul id={listId} className="smail-members">
                        {group.employees.map((employee) => (
                          <li key={employee.user_id}>
                            <label className="smail-check smail-member">
                              <input
                                type="checkbox"
                                checked={selectedKeys.includes(
                                  memberKey(group, employee)
                                )}
                                onChange={() =>
                                  toggleMember(memberKey(group, employee))
                                }
                              />
                              <span className="smail-member-text">
                                <span className="smail-member-name">
                                  {employee.full_name || employee.email}
                                </span>
                                {employee.full_name && (
                                  <span className="smail-member-email">
                                    {employee.email}
                                  </span>
                                )}
                              </span>
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
        </section>

        <section className="card smail-message" aria-labelledby="smail-message-title">
          <div className="card-header">
            <h2 id="smail-message-title" className="card-title">
              {t('schedule_mail.message')}
            </h2>
          </div>

          <div className="card-pad smail-fields">
            <label className="field">
              <span className="field-label">{t('schedule_mail.subject')}</span>
              <input
                type="text"
                className="input"
                maxLength={300}
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">{t('schedule_mail.body')}</span>
              <textarea
                className="textarea smail-textarea"
                rows={10}
                maxLength={5000}
                value={body}
                onChange={(event) => setBody(event.target.value)}
              />
            </label>

            {sendError && (
              <div className="alert alert-danger" role="alert">
                {sendError}
              </div>
            )}
          </div>

          <div className="smail-footer">
            <p className="smail-summary">
              {selectedPeople.length > 0
                ? selectedPeople.map((person) => person.name).join(', ')
                : t('schedule_mail.pick_hint')}
            </p>
            <button
              type="button"
              className="btn btn-primary smail-send"
              disabled={!canSend}
              onClick={() => setSendAsked(true)}
            >
              {busy ? (
                <span className="spinner smail-send-spinner" aria-hidden="true" />
              ) : (
                <MailIcon className="" />
              )}
              {t('schedule_mail.send')}
            </button>
          </div>
        </section>
      </div>

      <ConfirmDialog
        open={sendAsked}
        title={t('schedule_mail.send_confirm_title')}
        message={t('schedule_mail.send_confirm')}
        details={selectedPeople.map((person) => person.address).join(', ')}
        confirmLabel={t('schedule_mail.send')}
        cancelLabel={t('sidebar.cancel')}
        onConfirm={handleSend}
        onCancel={() => setSendAsked(false)}
      />

      <Toast message={toast} />
    </div>
  );
};

export default ScheduleMailView;
