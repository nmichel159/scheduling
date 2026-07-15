import { useState, useEffect } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import Header from '../components/Header';
import './MainLayout.css';

const SIDEBAR_KEY = 'sidebarOpen';
const isDesktop = () => window.matchMedia('(min-width: 769px)').matches;

/** Desktop: cached stav, inak defaultne otvorený. Mobil: vždy zatvorený. */
const getInitialSidebar = () => {
  if (!isDesktop()) return false;
  const saved = localStorage.getItem(SIDEBAR_KEY);
  return saved === null ? true : saved === 'true';
};

const MainLayout = () => {
  const [sidebarOpen, setSidebarOpen] = useState(getInitialSidebar);

  // Cache stavu — len na desktope, mobilný overlay si pamätať nechceme.
  useEffect(() => {
    if (isDesktop()) {
      localStorage.setItem(SIDEBAR_KEY, String(sidebarOpen));
    }
  }, [sidebarOpen]);

  if (!localStorage.getItem('user')) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="app-container">
      <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen(o => !o)} />
      {sidebarOpen && !isDesktop() && (
        <div className="backdrop" onClick={() => setSidebarOpen(false)} />
      )}
      <div className="main-area">
        <Header onToggle={() => setSidebarOpen(o => !o)} />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default MainLayout;