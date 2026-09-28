import { Link, isRouteErrorResponse, useRouteError } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useLandingPath } from '../hooks/useRoles';
import './RouteErrorView.css';

/**
 * Shown by the router instead of its bare default error screen: for an
 * unknown address (404) and for an exception thrown while rendering a page.
 */
const RouteErrorView = () => {
  const { t } = useTranslation();
  const error = useRouteError();
  const landingPath = useLandingPath();
  const notFound = isRouteErrorResponse(error) && error.status === 404;

  if (!notFound) console.error(error);

  return (
    <main className="route-error">
      <div className="route-error-card">
        <p className="route-error-code">{notFound ? t('route_error.not_found_code') : '!'}</p>
        <h1 className="route-error-title">
          {notFound ? t('route_error.not_found_title') : t('route_error.error_title')}
        </h1>
        <p className="route-error-text">
          {notFound ? t('route_error.not_found_text') : t('route_error.error_text')}
        </p>
        <div className="route-error-actions">
          {!notFound && (
            <button type="button" className="btn" onClick={() => window.location.reload()}>
              {t('route_error.reload')}
            </button>
          )}
          <Link to={localStorage.getItem('user') ? landingPath : '/'} className="btn btn-primary">
            {t('route_error.home')}
          </Link>
        </div>
      </div>
    </main>
  );
};

export default RouteErrorView;
