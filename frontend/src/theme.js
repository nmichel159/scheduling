/**
 * Voľba vzhľadu — svetlý, tmavý alebo podľa systému.
 *
 * Do <html> sa vždy zapíše až vyhodnotená téma (data-theme="light" | "dark"),
 * takže CSS si vystačí s jediným blokom tmavých premenných. Keby sa tam písala
 * surová voľba, každý tmavý blok by musel existovať dvakrát — raz pre ručnú
 * voľbu a raz v @media (prefers-color-scheme: dark) pre systémový režim.
 */

const STORAGE_KEY = 'theme';

/** 'system' je predvolený — kým si používateľ nevyberie, riadi to operačný systém. */
export const THEMES = ['system', 'light', 'dark'];

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
const listeners = new Set();

const readStoredTheme = () => {
  const saved = localStorage.getItem(STORAGE_KEY);
  return THEMES.includes(saved) ? saved : 'system';
};

let current = readStoredTheme();

const applyTheme = () => {
  const resolved = current === 'system' ? (darkQuery.matches ? 'dark' : 'light') : current;
  document.documentElement.dataset.theme = resolved;
};

const notify = () => listeners.forEach((listener) => listener());

export const getTheme = () => current;

export const setTheme = (theme) => {
  current = THEMES.includes(theme) ? theme : 'system';
  localStorage.setItem(STORAGE_KEY, current);
  applyTheme();
  notify();
};

export const subscribeTheme = (listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

// V systémovom režime musí appka reagovať aj na prepnutie počas behu
// (napr. keď Windows večer sám prepne na tmavý motív).
darkQuery.addEventListener('change', () => {
  if (current === 'system') {
    applyTheme();
    notify();
  }
});

// Zapísať ešte pred prvým vykreslením, aby appka neblikla v opačnom motíve.
applyTheme();
