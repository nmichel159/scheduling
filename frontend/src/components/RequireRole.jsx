import { Navigate } from 'react-router-dom';
import { useRoles } from '../hooks/useRoles';

/** Allows access only when the authenticated user has the requested role flag. */
const RequireRole = ({ flag, children }) => {
  const roles = useRoles();
  return roles[flag] ? children : <Navigate to="/dashboard" replace />;
};

export default RequireRole;
