import React from 'react';
import { useTranslation } from 'react-i18next';

const DashboardView = () => {
  const { t } = useTranslation();

  return (
    <div style={{ padding: '40px', textAlign: 'left' }}>
      <header style={{ marginBottom: '40px' }}>
        <h2 style={{ color: 'var(--accent)' }}>{t('welcome_back') || 'Vitaj späť!'}</h2>
        <p>Tu je tvoj prehľad úloh na dnes.</p>
      </header>
      
      <div style={{ 
        padding: '20px', 
        border: '1px solid var(--border)', 
        borderRadius: '12px',
        background: 'var(--social-bg)' 
      }}>
        <code>// Sem neskôr vložíme FullCalendar komponent</code>
      </div>
    </div>
  );
};

export default DashboardView;