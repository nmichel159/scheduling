import { useState } from 'react'
import axios from 'axios'

function App() {
  const [displayText, setDisplayText] = useState('Hello world')

  // 1. DYNAMICKÁ ADRESA BACKENDU
  // Vite hľadá premennú VITE_API_URL v systéme. 
  // Ak ju nenájde (napr. bežíš lokálne a nemáš .env), použije localhost:8000 ako zálohu.
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const loadMessage = async () => {
    try {
      // 2. POUŽITIE PREMENNEJ V AXIOS
      const response = await axios.get(`${API_URL}/message`)
      setDisplayText(response.data.message)
    } catch (error) {
      console.error("Error fetching the message:", error)
      setDisplayText("Error loading message")
    }
  }

  return (
    <div style={{ 
      padding: '2rem', 
      fontFamily: 'sans-serif', 
      textAlign: 'center',
      backgroundColor: '#f4f4f9',
      minHeight: '100vh' 
    }}>
      <h1>{displayText}</h1>
      <button 
        onClick={loadMessage} 
        style={{ 
          padding: '12px 24px', 
          fontSize: '16px', 
          cursor: 'pointer',
          backgroundColor: '#007bff',
          color: 'white',
          border: 'none',
          borderRadius: '4px',
          boxShadow: '0 2px 4px rgba(0,0,0,0.1)'
        }}
      >
        Load Message
      </button>
      
      {/* Pomôcka pre teba, aby si videl, kam sa práve pripájaš */}
      <p style={{ marginTop: '20px', fontSize: '12px', color: '#666' }}>
        Connecting to: {API_URL}
      </p>
    </div>
  )
}

export default App