import { createBrowserRouter } from 'react-router-dom';
import LoginView from '../views/LoginView';
import DashboardView from '../views/DashboardView';
import WorkloadView from '../views/WorkloadView';
import ScheduleView from '../views/ScheduleView';
import AmbulanceScheduleEditView from '../views/AmbulanceScheduleEditView';
import SchedulePrintView from '../views/SchedulePrintView';
import DepartmentsView from '../views/DepartmentsView';
import EmployeesView from '../views/EmployeesView';
import CompetenceManagerView from '../views/CompetenceManagerView';
import SpecialDaysView from '../views/SpecialDaysView';
import ScheduleMailView from '../views/ScheduleMailView';
import AdminView from '../views/AdminView';
import ScheduleOverviewView from '../views/ScheduleOverviewView';
import StatisticsView from '../views/StatisticsView';
import RoleManagementView from '../views/RoleManagementView';
import MainLayout from '../layouts/MainLayout';
import RequireRole from '../components/RequireRole';

/** Pustí ďalej len usera s daným flagom roly (UX vrstva, backend má vlastné 403). */
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
        element: (
          <RequireRole flag="hasEmployee">
            <DashboardView />
          </RequireRole>
        ),
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
        // A sibling of /ambulances/schedule rather than a child of it: the
        // sidebar marks a link active for its whole subtree, and a nested path
        // would light up the editor's entry as well as this one.
        path: "/ambulances/print",
        element: (
          <RequireRole flag="hasManager">
            <SchedulePrintView />
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
        path: "/employees",
        element: (
          <RequireRole flag="hasManager">
            <EmployeesView />
          </RequireRole>
        ),
      },
      {
        path: "/competences",
        element: (
          <RequireRole flag="hasManager">
            <CompetenceManagerView />
          </RequireRole>
        ),
      },
      {
        path: "/ambulances/mail",
        element: (
          <RequireRole flag="hasManager">
            <ScheduleMailView />
          </RequireRole>
        ),
      },
      {
        path: "/special-days",
        element: (
          <RequireRole flag={["hasManager", "hasAdmin"]}>
            <SpecialDaysView />
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
      {
        path: "/schedules/overview",
        element: (
          <RequireRole flag="hasAdmin">
            <ScheduleOverviewView />
          </RequireRole>
        ),
      },
      {
        path: "/statistics",
        element: (
          <RequireRole flag="hasAnalyst">
            <StatisticsView />
          </RequireRole>
        ),
      },
      {
        path: "/roles",
        element: (
          <RequireRole flag="hasAdmin">
            <RoleManagementView />
          </RequireRole>
        ),
      },
      // Sem môžeš neskôr pridať /settings, /profile atď.
    ],
  },
]);
