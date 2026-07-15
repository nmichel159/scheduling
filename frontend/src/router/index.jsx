import { createBrowserRouter, Navigate } from 'react-router-dom';
import LoginView from '../views/LoginView';
import DashboardView from '../views/DashboardView';
import WorkloadView from '../views/WorkloadView';
import DepartmentsView from '../views/DepartmentsView';
import AdminView from '../views/AdminView';
import MainLayout from '../layouts/MainLayout';
import { useRoles } from '../hooks/useRoles';

/** Pustí ďalej len usera s dostatočným role levelom (UX vrstva, backend má vlastné 403). */
const RequireRole = ({ minLevel, children }) => {
  const { maxLevel } = useRoles();
  return maxLevel >= minLevel ? children : <Navigate to="/dashboard" replace />;
};

export const router = createBrowserRouter([
  {
    path: "/",
    element: <LoginView />,
  },
  {
    element: <MainLayout />, // Obal pre chránené cesty
    children: [
      {
        path: "/dashboard",
        element: <DashboardView />,
      },
      {
        path: "/workload",
        element: <WorkloadView />,
      },
      {
        path: "/departments",
        element: (
          <RequireRole minLevel={2}>
            <DepartmentsView />
          </RequireRole>
        ),
      },
      {
        path: "/admin",
        element: (
          <RequireRole minLevel={3}>
            <AdminView />
          </RequireRole>
        ),
      },
      // Sem môžeš neskôr pridať /settings, /profile atď.
    ],
  },
]);