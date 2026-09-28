import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import sk from './locales/sk.json';
import en from './locales/en.json';

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      sk: { translation: sk }
    },
    supportedLngs: ['sk', 'en'],
    fallbackLng: 'sk',
    // The browser reports "sk-SK" / "en-US"; keep only the language so the
    // app always runs in exactly "sk" or "en" and comparisons like
    // i18n.language === 'sk' hold.
    detection: {
      convertDetectedLanguage: (lng) => lng.split('-')[0],
    },
    interpolation: { escapeValue: false }
  });

// Screen readers and hyphenation read the page language from <html lang>.
const syncHtmlLang = (lng) => {
  document.documentElement.lang = (lng || 'sk').split('-')[0];
  // index.html ships the Slovak name; an English session should not keep it.
  document.title = i18n.t('app_title');
};
syncHtmlLang(i18n.resolvedLanguage);
i18n.on('languageChanged', syncHtmlLang);

export default i18n;
