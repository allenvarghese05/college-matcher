import React, { createContext, useContext, useState } from 'react';
import { Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Home from './pages/Home';
import Assessment from './pages/Assessment';
import Results from './pages/Results';
import BrowseSchools from './pages/BrowseSchools';
import SchoolDetail from './pages/SchoolDetail';
import SchoolProfile from './pages/SchoolProfile';
import CareerAssessment from './pages/CareerAssessment';
import CareerResults from './pages/CareerResults';
import './App.css';

// Create theme context
const ThemeContext = createContext();

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

function App() {
  const [isDarkMode, setIsDarkMode] = useState(false);

  const toggleDarkMode = () => {
    setIsDarkMode(!isDarkMode);
    document.body.classList.toggle('dark-mode');
  };

  return (
    <ThemeContext.Provider value={{ isDarkMode, toggleDarkMode }}>
      <div className={`App ${isDarkMode ? 'dark-mode' : ''}`}>
        <Navbar />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/assessment" element={<Assessment />} />
          <Route path="/results" element={<Results />} />
          <Route path="/schools" element={<BrowseSchools />} />
          <Route path="/school/:id" element={<SchoolProfile />} />
          <Route path="/school-detail/:id" element={<SchoolDetail />} />
          <Route path="/career-assessment" element={<CareerAssessment />} />
          <Route path="/career-results" element={<CareerResults />} />
        </Routes>
      </div>
    </ThemeContext.Provider>
  );
}

export default App; 