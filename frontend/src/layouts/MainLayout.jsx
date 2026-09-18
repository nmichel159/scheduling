import { useState, useEffect } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import Header from '../components/Header';
import { useMediaQuery, DESKTOP_QUERY } from '../hooks/useMediaQuery';
import { WorkplaceProvider } from '../hooks/WorkplaceProvider';
import './MainLayout.css';

const SIDEBAR_KEY = 'sidebarOpen';

/** Desktop: cached stav, inak defaultne otvorený. Mobil: vždy zatvorený. */
const getInitialSidebar = () => {
  if (!window.matchMedia(DESKTOP_QUERY).matches) return false;
  const saved = localStorage.getItem(SIDEBAR_KEY);
  return saved === null ? true : saved === 'true';
};

const MainLayout = () => {
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const [sidebarOpen, setSidebarOpen] = useState(getInitialSidebar);

  // Cache stavu — len na desktope, mobilný overlay si pamätať nechceme.
  useEffect(() => {
    if (isDesktop) {
      localStorage.setItem(SIDEBAR_KEY, String(sidebarOpen));
    }
  }, [sidebarOpen, isDesktop]);

  // Po zmene veľkosti okna: na mobile sa overlay zavrie, na desktope sa obnoví
  // zapamätaná voľba (rail alebo vypísané položky).
  useEffect(() => {
    setSidebarOpen(isDesktop ? localStorage.getItem(SIDEBAR_KEY) !== 'false' : false);
  }, [isDesktop]);

  if (!localStorage.getItem('user')) {
    return <Navigate to="/" replace />;
  }

  return (
    <WorkplaceProvider>
      <div className="app-container">
        <Sidebar
          open={sidebarOpen}
          onToggle={() => setSidebarOpen((o) => !o)}
          onClose={() => setSidebarOpen(false)}
        />
        {sidebarOpen && !isDesktop && (
          <div className="backdrop" onClick={() => setSidebarOpen(false)} />
        )}
        <div className="main-area">
          <Header onToggle={() => setSidebarOpen((o) => !o)} />
          <main className="content">
            <Outlet />
          </main>
        </div>
      </div>
    </WorkplaceProvider>
  );
};

export default MainLayout;
