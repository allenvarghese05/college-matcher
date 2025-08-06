import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { GraduationCap, Moon, Sun } from 'lucide-react';
import { useTheme } from '../App';

const Navbar = () => {
  const location = useLocation();
  const { isDarkMode, toggleDarkMode } = useTheme();

  const isActive = (path) => {
    return location.pathname === path;
  };

  return (
    <nav className="navbar">
      <div className="navbar-container">
        <Link to="/" className="navbar-brand">
          <GraduationCap className="navbar-logo" />
          <span>College Matcher</span>
        </Link>
        
        <div className="navbar-links">
          <Link 
            to="/" 
            className={`navbar-link ${isActive('/') ? 'active' : ''}`}
          >
            Home
          </Link>
          <Link 
            to="/assessment" 
            className={`navbar-link ${isActive('/assessment') ? 'active' : ''}`}
          >
            College Assessment
          </Link>
          <Link 
            to="/career-assessment" 
            className={`navbar-link ${isActive('/career-assessment') ? 'active' : ''}`}
          >
            Career Assessment
          </Link>
          <Link 
            to="/schools" 
            className={`navbar-link ${isActive('/schools') ? 'active' : ''}`}
          >
            Browse Schools
          </Link>
        </div>

        <div className="navbar-actions">
          <button 
            onClick={toggleDarkMode}
            className="theme-toggle"
            aria-label="Toggle dark mode"
          >
            {isDarkMode ? <Sun size={20} /> : <Moon size={20} />}
          </button>
        </div>
      </div>

      <style jsx="true">{`
        .navbar {
          background: var(--card-bg);
          border-bottom: 1px solid var(--border-color);
          padding: 1rem 0;
          position: sticky;
          top: 0;
          z-index: 1000;
          backdrop-filter: blur(10px);
          box-shadow: 0 1px 3px var(--shadow-color);
        }

        .navbar-container {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 2rem;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .navbar-brand {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--text-primary);
          text-decoration: none;
          transition: all 0.2s ease;
        }

        .navbar-brand:hover {
          color: var(--primary-color);
          transform: translateY(-1px);
        }

        .navbar-logo {
          color: var(--primary-color);
        }

        .navbar-links {
          display: flex;
          align-items: center;
          gap: 2rem;
        }

        .navbar-link {
          color: var(--text-secondary);
          text-decoration: none;
          font-weight: 500;
          padding: 0.5rem 1rem;
          border-radius: 8px;
          transition: all 0.2s ease;
          position: relative;
        }

        .navbar-link:hover {
          color: var(--text-primary);
          background-color: var(--bg-secondary);
        }

        .navbar-link.active {
          color: var(--primary-color);
          background-color: var(--bg-secondary);
        }

        .navbar-link.active::after {
          content: '';
          position: absolute;
          bottom: -1rem;
          left: 50%;
          transform: translateX(-50%);
          width: 20px;
          height: 2px;
          background-color: var(--primary-color);
          border-radius: 1px;
        }

        .navbar-actions {
          display: flex;
          align-items: center;
          gap: 1rem;
        }

        .theme-toggle {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          color: var(--text-primary);
          padding: 0.5rem;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s ease;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .theme-toggle:hover {
          background: var(--bg-tertiary);
          transform: translateY(-1px);
          box-shadow: 0 2px 8px var(--shadow-color);
        }

        @media (max-width: 768px) {
          .navbar-container {
            padding: 0 1rem;
            flex-direction: column;
            gap: 1rem;
          }

          .navbar-links {
            gap: 1rem;
            flex-wrap: wrap;
            justify-content: center;
          }

          .navbar-link {
            padding: 0.25rem 0.5rem;
            font-size: 0.875rem;
          }
        }
      `}</style>
    </nav>
  );
};

export default Navbar; 