import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
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

/** "Detska" has to find "Detská" too -- lower-case, accents stripped. */
const normalize = (value) =>
  (value || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

/** Above this many workplaces the list stops being scannable by eye. */
const FILTER_THRESHOLD = 7;

/** Gap between the trigger and the menu it opens. */
const MENU_GAP = 6;

/**
 * The one place a scheduler picks which workplace they are working on.
 * It reads the same on every scheduler screen and survives navigation
 * between them.
 *
 * Props:
 * - variant: 'sidebar' (desktop: the top of the side bar, under the logo) or
 *   'header' (mobile: the middle of the top bar).
 * - rail: the side bar is collapsed, so only the badge is drawn and the menu
 *   opens beside it instead of under it.
 * - open / onOpenChange: optional. The side bar passes them so that this
 *   menu and its own fly-outs are never open at the same time.
 */
const WorkplaceSwitcher = ({
  variant = 'header',
  rail = false,
  open: controlledOpen,
  onOpenChange,
}) => {
  const { t } = useTranslation();
  const { workplaces, activeId, active, loading, error, setActive, isSwitchBlocked } =
    useWorkplace();

  const inSidebar = variant === 'sidebar';

  const [ownOpen, setOwnOpen] = useState(false);
  const open = controlledOpen ?? ownOpen;
  const [filter, setFilter] = useState('');
  const [pendingId, setPendingId] = useState(null); // awaiting unsaved-changes confirm
  const [menuPosition, setMenuPosition] = useState(null);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const menuRef = useRef(null);

  const setOpen = useCallback(
    (next) => {
      if (onOpenChange) onOpenChange(next);
      else setOwnOpen(next);
    },
    [onOpenChange]
  );

  const close = useCallback(() => {
    setOpen(false);
    setFilter('');
  }, [setOpen]);

  /* In the side bar the menu is position: fixed and drawn in a portal: the
   * bar clips its overflow, and the menu has to lie over the page beside it.
   * Under the trigger while the bar is spelled out, beside the badge in the
   * rail. */
  const toggle = () => {
    if (open) {
      close();
      return;
    }
    if (inSidebar && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setMenuPosition(
        rail
          ? { top: rect.top, left: rect.right + MENU_GAP + 8 }
          : { top: rect.bottom + MENU_GAP, left: rect.left, minWidth: rect.width }
      );
    }
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (e) => {
      if (rootRef.current?.contains(e.target) || menuRef.current?.contains(e.target)) return;
      close();
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    // The fixed menu was placed from where the trigger stood.
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize', close);
    };
  }, [open, close]);

  // Regular workplaces first, then the emergency ones -- the same split the
  // departments page used to draw, kept because "urgentný príjem" is staffed
  // from the other rosters and reads as a different kind of thing.
  const groups = useMemo(() => {
    const needle = normalize(filter.trim());
    const matching = needle
      ? workplaces.filter((w) =>
          normalize(`${w.name} ${w.description || ''}`).includes(needle)
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

  const rootClass = [
    'workplace-switcher',
    inSidebar && 'is-sidebar',
    rail && 'is-rail',
  ]
    .filter(Boolean)
    .join(' ');

  if (loading) {
    return inSidebar ? (
      <div className={rootClass}>
        <span className="skeleton workplace-switcher-skeleton" />
      </div>
    ) : (
      <span className="workplace-switcher-status">{t('workplace.loading')}</span>
    );
  }
  if (error) {
    // The rail has no room for a sentence; the screens that need a workplace
    // report the failure themselves.
    if (rail) return null;
    return <span className="workplace-switcher-status">{t('workplace.load_error')}</span>;
  }
  if (workplaces.length === 0) return null;

  // Nothing to switch between: show where you are, without a control that
  // would open onto a list of one.
  if (workplaces.length === 1) {
    return (
      <div className={`${rootClass} is-static`} title={rail ? active?.name : undefined}>
        <span className="workplace-switcher-badge" aria-hidden="true">
          {initialsOf(active?.name)}
        </span>
        <span className="workplace-switcher-name">{active?.name}</span>
      </div>
    );
  }

  const menu = open && (
    <div
      ref={menuRef}
      className={`workplace-switcher-menu ${inSidebar ? 'is-floating' : ''}`}
      style={inSidebar ? menuPosition : undefined}
      role="listbox"
    >
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
  );

  return (
    <div className={rootClass} ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className="workplace-switcher-trigger"
        onClick={toggle}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('workplace.switch_label')}
        title={rail ? active?.name : undefined}
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

      {inSidebar ? menu && createPortal(menu, document.body) : menu}

      {/* In a portal: both bars this control sits in are stacking contexts
          of their own, and a dialog drawn inside one would lie under
          whatever the page stacks higher. */}
      {createPortal(
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
        />,
        document.body
      )}
    </div>
  );
};

export default WorkplaceSwitcher;
