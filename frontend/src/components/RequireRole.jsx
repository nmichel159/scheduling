import { Navigate } from 'react-router-dom';
import { useRoles, landingPathFor } from '../hooks/useRoles';

/** Allows access only when the authenticated user has the requested role flag. */
const RequireRole = ({ flag, children }) => {
  const roles = useRoles();
  if (roles[flag]) return children;
  // Nie na /dashboard — ten je sám zamestnanecký a odmietnutý používateľ by
  // sa medzi ním a touto cestou točil dokola.
  return <Navigate to={landingPathFor(roles.roles)} replace />;
};

export default RequireRole;
