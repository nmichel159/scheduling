import React from 'react';

const DashboardView = () => {
  // Vytiahneme dáta, ktoré sme v LoginView uložili do localStorage
  const userString = localStorage.getItem('user');
  const user = userString ? JSON.parse(userString) : null;

  if (!user) {
    return <h1>Prosím, prihláste sa.</h1>;
  }

  return (
    <div style={{ padding: '40px', textAlign: 'center' }}>
      <h1>Vitaj, {user.full_name}! 👋</h1>
      <p>Email: {user.email}</p>
      
      <div style={{ 
        marginTop: '20px', 
        padding: '20px', 
        border: '2px solid #646cff',
        borderRadius: '12px',
        display: 'inline-block'
      }}>
        <h2>Štatistika prihlásení</h2>
        <p style={{ fontSize: '2rem', fontWeight: 'bold', color: '#646cff' }}>
          {user.login_count}
        </p>
        <p>krát si sa úspešne prihlásil do systému.</p>
      </div>
    </div>
  );
};

export default DashboardView;