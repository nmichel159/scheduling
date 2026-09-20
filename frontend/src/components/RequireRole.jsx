import { Navigate } from 'react-router-dom';
import { useRoles, landingPathFor } from '../hooks/useRoles';

/**
 * Allows access only when the authenticated user has the requested role flag.
 *
 * `flag` may be a list, for a screen two tiers reach for different reasons —
 * the special-day calendar is the administrator's to set and the scheduler's
 * to read, and neither role implies the other.
 */
const RequireRole = ({ flag, children }) => {
  const roles = useRoles();
  const flags = Array.isArray(flag) ? flag : [flag];
  if (flags.some((name) => roles[name])) return children;
  // Nie na /dashboard — ten je sám zamestnanecký a odmietnutý používateľ by
  // sa medzi ním a touto cestou točil dokola.
  return <Navigate to={landingPathFor(roles.roles)} replace />;
};

export default RequireRole;
