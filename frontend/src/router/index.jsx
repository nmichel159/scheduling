import { createBrowserRouter, Navigate } from 'react-router-dom';
import LoginView from '../views/LoginView';
import DashboardView from '../views/DashboardView';
import WorkloadView from '../views/WorkloadView';
import ScheduleView from '../views/ScheduleView';
import AmbulanceScheduleEditView from '../views/AmbulanceScheduleEditView';
import DepartmentsView from '../views/DepartmentsView';
import AdminView from '../views/AdminView';
import MainLayout from '../layouts/MainLayout';
import { useRoles } from '../hooks/useRoles';

/** Pustí ďalej len usera s daným flagom roly (UX vrstva, backend má vlastné 403). */
const RequireRole = ({ flag, children }) => {
  const roles = useRoles();
  return roles[flag] ? children : <Navigate to="/dashboard" replace />;
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
        element: (
          <RequireRole flag="hasEmployee">
            <WorkloadView />
          </RequireRole>
        ),
      },
      {
        path: "/schedule",
        element: (
          <RequireRole flag="hasEmployee">
            <ScheduleView />
          </RequireRole>
        ),
      },
      {
        path: "/ambulances/schedule",
        element: (
          <RequireRole flag="hasManager">
            <AmbulanceScheduleEditView />
          </RequireRole>
        ),
      },
      {
        path: "/departments",
        element: (
          <RequireRole flag="hasManager">
            <DepartmentsView />
          </RequireRole>
        ),
      },
      {
        path: "/admin",
        element: (
          <RequireRole flag="hasAdmin">
            <AdminView />
          </RequireRole>
        ),
      },
      // Sem môžeš neskôr pridať /settings, /profile atď.
    ],
  },
]);