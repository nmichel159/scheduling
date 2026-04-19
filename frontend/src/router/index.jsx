import { createBrowserRouter } from 'react-router-dom';
import LoginView from '../views/LoginView';
import DashboardView from '../views/DashboardView';
import MainLayout from '../layouts/MainLayout';

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
      // Sem môžeš neskôr pridať /settings, /profile atď.
    ],
  },
]);