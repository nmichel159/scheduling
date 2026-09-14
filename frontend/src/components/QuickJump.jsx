import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { SearchIcon } from './NavIcons';
import './QuickJump.css';

/** "Rozpís" musí nájsť aj ten, kto píše bez diakritiky. */
const normalize = (value) =>
  value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');

/**
 * Rýchly skok na obrazovku (Ctrl/⌘ + K).
 *
 * Props:
 * - open: či je paleta otvorená
 * - items: [{ to, label, section }] — už prefiltrované podľa rolí používateľa
 * - onClose: zavretie palety
 */
const QuickJump = ({ open, items, onClose }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const inputRef = useRef(null);

  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);

  const matches = useMemo(() => {
    const needle = normalize(query.trim());
    if (!needle) return items;
    return items.filter(
      (item) =>
        normalize(item.label).includes(needle) ||
        normalize(item.section || '').includes(needle),
    );
  }, [items, query]);

  // Pri každom otvorení sa začína odznova a kurzor nesmie ostať mimo zoznamu.
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setCursor(0);
    inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    setCursor((current) => Math.min(current, Math.max(matches.length - 1, 0)));
  }, [matches.length]);

  if (!open) return null;

  const go = (item) => {
    if (!item) return;
    onClose();
    navigate(item.to);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor((c) => (matches.length ? (c + 1) % matches.length : 0));
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor((c) => (matches.length ? (c - 1 + matches.length) % matches.length : 0));
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      go(matches[cursor]);
    }
  };

  return (
    <div
      className="quick-jump-overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="quick-jump" role="dialog" aria-modal="true" aria-label={t('sidebar.quick_jump')}>
        <div className="quick-jump-field">
          <SearchIcon className="quick-jump-icon" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('sidebar.quick_jump_placeholder')}
            aria-label={t('sidebar.quick_jump_placeholder')}
            autoComplete="off"
          />
          <kbd className="quick-jump-kbd">Esc</kbd>
        </div>

        {matches.length === 0 ? (
          <p className="quick-jump-empty">{t('sidebar.quick_jump_empty')}</p>
        ) : (
          <ul className="quick-jump-list">
            {matches.map((item, index) => (
              <li key={item.to}>
                <button
                  type="button"
                  className={`quick-jump-item ${index === cursor ? 'is-cursor' : ''}`}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => go(item)}
                >
                  <item.Icon className="nav-icon" />
                  <span className="quick-jump-label">{item.label}</span>
                  {item.section && <span className="quick-jump-section">{item.section}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default QuickJump;
