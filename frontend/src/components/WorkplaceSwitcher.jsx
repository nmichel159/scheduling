import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkplace } from '../hooks/workplaceContext';
import ConfirmDialog from './ConfirmDialog';
import { ChevronDownIcon } from './NavIcons';
import './WorkplaceSwitcher.css';

/** "I. KAIM" -> "IK"; the rail-style badge in front of the name. */
const initialsOf = (name) =>
  (name || '')
    .split(/[\s.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join('')
    .toUpperCase() || '?';

/** Above this many workplaces the list stops being scannable by eye. */
const FILTER_THRESHOLD = 7;

/**
 * The one place a scheduler picks which workplace they are working on.
 * Lives in the header, so it reads the same on every scheduler screen and
 * survives navigation between them.
 */
const WorkplaceSwitcher = () => {
  const { t } = useTranslation();
  const { workplaces, activeId, active, loading, error, setActive, isSwitchBlocked } =
    useWorkplace();

  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState('');
  const [pendingId, setPendingId] = useState(null); // awaiting unsaved-changes confirm
  const rootRef = useRef(null);

  const close = useCallback(() => {
    setOpen(false);
    setFilter('');
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (!rootRef.current?.contains(e.target)) close();
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, close]);

  // Regular workplaces first, then the emergency ones -- the same split the
  // departments page used to draw, kept because "urgentný príjem" is staffed
  // from the other rosters and reads as a different kind of thing.
  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matching = needle
      ? workplaces.filter((w) =>
          `${w.name} ${w.description || ''}`.toLowerCase().includes(needle)
        )
      : workplaces;
    const regular = matching.filter((w) => !w.isurgent);
    const urgent = matching.filter((w) => w.isurgent);
    return { regular, urgent, total: matching.length, split: regular.length > 0 && urgent.length > 0 };
  }, [workplaces, filter]);

  const renderOption = (w) => (
    <button
      type="button"
      key={w.id}
      role="option"
      aria-selected={w.id === activeId}
      className={`workplace-switcher-option ${w.id === activeId ? 'is-selected' : ''}`}
      onClick={() => choose(w.id)}
    >
      <span className="workplace-switcher-badge" aria-hidden="true">
        {initialsOf(w.name)}
      </span>
      <span className="workplace-switcher-option-text">
        <span className="workplace-switcher-option-name">{w.name}</span>
        {w.description && (
          <span className="workplace-switcher-option-desc">{w.description}</span>
        )}
      </span>
    </button>
  );

  const choose = (id) => {
    close();
    if (id === activeId) return;
    if (isSwitchBlocked()) {
      setPendingId(id);
      return;
    }
    setActive(id);
  };

  if (loading) {
    return <span className="workplace-switcher-status">{t('workplace.loading')}</span>;
  }
  if (error) {
    return <span className="workplace-switcher-status">{t('workplace.load_error')}</span>;
  }
  if (workplaces.length === 0) return null;

  // Nothing to switch between: show where you are, without a control that
  // would open onto a list of one.
  if (workplaces.length === 1) {
    return (
      <div className="workplace-switcher is-static">
        <span className="workplace-switcher-badge" aria-hidden="true">
          {initialsOf(active?.name)}
        </span>
        <span className="workplace-switcher-name">{active?.name}</span>
      </div>
    );
  }

  return (
    <div className="workplace-switcher" ref={rootRef}>
      <button
        type="button"
        className="workplace-switcher-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('workplace.switch_label')}
      >
        <span className="workplace-switcher-badge" aria-hidden="true">
          {initialsOf(active?.name)}
        </span>
        <span className="workplace-switcher-name">
          {active?.name || t('workplace.none_selected')}
        </span>
        <ChevronDownIcon
          className={`workplace-switcher-caret ${open ? 'is-open' : ''}`}
        />
      </button>

      {open && (
        <div className="workplace-switcher-menu" role="listbox">
          {workplaces.length > FILTER_THRESHOLD && (
            <input
              type="text"
              className="workplace-switcher-filter"
              value={filter}
              autoFocus
              placeholder={t('workplace.filter_placeholder')}
              onChange={(e) => setFilter(e.target.value)}
            />
          )}

          <div className="workplace-switcher-list">
            {[
              { key: 'regular', items: groups.regular, titleKey: 'workplace.group_regular' },
              { key: 'urgent', items: groups.urgent, titleKey: 'workplace.group_urgent' },
            ].map(({ key, items, titleKey }) =>
              items.length === 0 ? null : (
                <div className="workplace-switcher-group" key={key}>
                  {groups.split && (
                    <p className="workplace-switcher-group-title">{t(titleKey)}</p>
                  )}
                  {items.map(renderOption)}
                </div>
              )
            )}
            {groups.total === 0 && (
              <p className="workplace-switcher-empty">{t('workplace.no_match')}</p>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={pendingId != null}
        message={t('workplace.unsaved_warning')}
        confirmLabel={t('workplace.switch_anyway')}
        cancelLabel={t('workplace.stay')}
        onConfirm={() => {
          setActive(pendingId);
          setPendingId(null);
        }}
        onCancel={() => setPendingId(null)}
      />
    </div>
  );
};

export default WorkplaceSwitcher;
