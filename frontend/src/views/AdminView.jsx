import { useTranslation } from 'react-i18next';

/**
 * Administration view for Role 3+ (ambulance codebook, manager assignment).
 * Placeholder — the actual editor is built in the next step.
 */
const AdminView = () => {
  const { t } = useTranslation();
  return (
    <div style={{ maxWidth: 960, margin: '0 auto', textAlign: 'left' }}>
      <h1>{t('sidebar.admin')}</h1>
      <p>{t('admin.coming_soon')}</p>
    </div>
  );
};

export default AdminView;