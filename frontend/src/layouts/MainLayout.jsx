import React from 'react';
import { Outlet, Link } from 'react-router-dom';
import './MainLayout.css';

const MainLayout = () => {
  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="logo">S</div>
        <nav>
          <Link to="/dashboard" className="nav-item">📅</Link>
          <Link to="/settings" className="nav-item">⚙️</Link>
        </nav>
        <div className="user-avatar">👤</div>
      </aside>
      
      <main className="content">
        <Outlet /> {/* Tu sa bude vykresľovať konkrétna podstránka */}
      </main>
    </div>
  );
};

export default MainLayout;