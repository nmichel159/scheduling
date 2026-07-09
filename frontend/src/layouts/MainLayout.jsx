import { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import Header from '../components/Header';
import './MainLayout.css';

const MainLayout = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);

    if (!localStorage.getItem('user')) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="app-container">
      <Sidebar open={sidebarOpen} onToggle={() => setSidebarOpen(o => !o)} />
      {sidebarOpen && (
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