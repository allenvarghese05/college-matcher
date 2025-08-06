import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Star, MapPin, Users, DollarSign, TrendingUp, Filter, Search } from 'lucide-react';
import { useTheme } from '../App';

const Results = ({ assessmentData, matches }) => {
  const { isDarkMode } = useTheme();
  const [filteredMatches, setFilteredMatches] = useState(matches || []);
  const [filters, setFilters] = useState({
    location: '',
    maxCost: '',
    minGPA: '',
    maxAcceptanceRate: '',
    minPopulation: '',
    maxPopulation: ''
  });
  const [sortBy, setSortBy] = useState('matchScore');

  useEffect(() => {
    if (matches) {
      setFilteredMatches(matches);
    }
  }, [matches]);

  const handleFilterChange = (field, value) => {
    const newFilters = { ...filters, [field]: value };
    setFilters(newFilters);
    
    let filtered = matches || [];
    
    if (newFilters.location) {
      filtered = filtered.filter(school => 
        school.location.toLowerCase().includes(newFilters.location.toLowerCase())
      );
    }
    
    if (newFilters.maxCost) {
      filtered = filtered.filter(school => 
        school.tuition <= parseInt(newFilters.maxCost)
      );
    }
    
    if (newFilters.minGPA) {
      filtered = filtered.filter(school => 
        school.averageGPA >= parseFloat(newFilters.minGPA)
      );
    }
    
    if (newFilters.maxAcceptanceRate) {
      filtered = filtered.filter(school => 
        school.acceptanceRate <= parseInt(newFilters.maxAcceptanceRate)
      );
    }
    
    if (newFilters.minPopulation) {
      filtered = filtered.filter(school => 
        school.studentPopulation >= parseInt(newFilters.minPopulation)
      );
    }
    
    if (newFilters.maxPopulation) {
      filtered = filtered.filter(school => 
        school.studentPopulation <= parseInt(newFilters.maxPopulation)
      );
    }
    
    setFilteredMatches(filtered);
  };

  const handleSort = (field) => {
    setSortBy(field);
    const sorted = [...filteredMatches].sort((a, b) => {
      if (field === 'matchScore') {
        return b.matchScore - a.matchScore;
      } else if (field === 'tuition') {
        return a.tuition - b.tuition;
      } else if (field === 'acceptanceRate') {
        return a.acceptanceRate - b.acceptanceRate;
      } else if (field === 'averageGPA') {
        return b.averageGPA - a.averageGPA;
      }
      return 0;
    });
    setFilteredMatches(sorted);
  };

  const getMatchScoreColor = (score) => {
    if (score >= 85) return '#10b981'; // Perfect Match
    if (score >= 70) return '#059669'; // Excellent Match
    if (score >= 55) return '#f59e0b'; // Good Match
    if (score >= 40) return '#d97706'; // Fair Match
    return '#ef4444'; // Poor Match
  };

  const getMatchScoreLabel = (score) => {
    if (score >= 85) return 'Perfect Match';
    if (score >= 70) return 'Excellent Match';
    if (score >= 55) return 'Good Match';
    if (score >= 40) return 'Fair Match';
    return 'Poor Match';
  };

  const getAdmissionCategoryColor = (category) => {
    switch (category) {
      case 'Safety': return '#10b981';
      case 'Target': return '#f59e0b';
      case 'Reach': return '#ef4444';
      default: return '#6b7280';
    }
  };

  if (!matches || matches.length === 0) {
    return (
      <div className="results">
        <div className="no-results">
          <h2>No Results Found</h2>
          <p>It looks like we couldn't find any schools that match your criteria. Try adjusting your preferences or take the assessment again.</p>
          <Link to="/assessment" className="btn btn-primary">
            Retake Assessment
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="results">
      <div className="results-header">
        <div className="results-intro">
          <h1>Your College Matches</h1>
          <p>Based on your assessment, here are the schools that best match your profile:</p>
          {assessmentData && (
            <div className="profile-summary">
              <h3>Your Profile Summary</h3>
              <div className="profile-grid">
                <div className="profile-item">
                  <strong>Major:</strong> {assessmentData.desiredMajor || 'Not specified'}
                </div>
                <div className="profile-item">
                  <strong>GPA:</strong> {assessmentData.currentGPA || 'Not specified'}
                </div>
                <div className="profile-item">
                  <strong>Budget:</strong> ${assessmentData.maxBudget || 'Not specified'}
                </div>
                <div className="profile-item">
                  <strong>Personality:</strong> {assessmentData.personalityType || 'Not specified'}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="filters-section">
        <div className="filters-header">
          <Filter size={20} />
          <h3>Filter & Sort Results</h3>
        </div>
        
        <div className="filters-grid">
          <div className="filter-group">
            <label>Location</label>
            <input
              type="text"
              placeholder="e.g., California"
              value={filters.location}
              onChange={(e) => handleFilterChange('location', e.target.value)}
            />
          </div>
          
          <div className="filter-group">
            <label>Max Tuition</label>
            <input
              type="number"
              placeholder="e.g., 50000"
              value={filters.maxCost}
              onChange={(e) => handleFilterChange('maxCost', e.target.value)}
            />
          </div>
          
          <div className="filter-group">
            <label>Min GPA</label>
            <input
              type="number"
              step="0.1"
              min="0"
              max="4.0"
              placeholder="e.g., 3.5"
              value={filters.minGPA}
              onChange={(e) => handleFilterChange('minGPA', e.target.value)}
            />
          </div>
          
          <div className="filter-group">
            <label>Max Acceptance Rate (%)</label>
            <input
              type="number"
              min="0"
              max="100"
              placeholder="e.g., 20"
              value={filters.maxAcceptanceRate}
              onChange={(e) => handleFilterChange('maxAcceptanceRate', e.target.value)}
            />
          </div>
          
          <div className="filter-group">
            <label>Min Student Population</label>
            <input
              type="number"
              placeholder="e.g., 10000"
              value={filters.minPopulation}
              onChange={(e) => handleFilterChange('minPopulation', e.target.value)}
            />
          </div>
          
          <div className="filter-group">
            <label>Max Student Population</label>
            <input
              type="number"
              placeholder="e.g., 50000"
              value={filters.maxPopulation}
              onChange={(e) => handleFilterChange('maxPopulation', e.target.value)}
            />
          </div>
        </div>
        
        <div className="sort-options">
          <label>Sort by:</label>
          <select value={sortBy} onChange={(e) => handleSort(e.target.value)}>
            <option value="matchScore">Match Score</option>
            <option value="tuition">Tuition (Low to High)</option>
            <option value="acceptanceRate">Acceptance Rate (Low to High)</option>
            <option value="averageGPA">Average GPA (High to Low)</option>
          </select>
        </div>
      </div>

      {/* Results */}
      <div className="results-content">
        <div className="results-count">
          <p>Showing {filteredMatches.length} of {matches.length} matches</p>
        </div>
        
        <div className="schools-grid">
          {filteredMatches.map((school) => (
            <div key={school.id} className="school-card">
              <div className="school-header">
                <img 
                  src={school.image} 
                  alt={school.name}
                  className="school-image"
                  onError={(e) => {
                    e.target.src = 'https://images.unsplash.com/photo-1523050854058-8df90110c9d1?w=400';
                  }}
                />
                <div className="match-score">
                  <div 
                    className="score-circle"
                    style={{ backgroundColor: getMatchScoreColor(school.matchScore) }}
                  >
                    {school.matchScore}
                  </div>
                  <span className="score-label">{getMatchScoreLabel(school.matchScore)}</span>
                  {school.admissionCategory && (
                    <div 
                      className="admission-category"
                      style={{ backgroundColor: getAdmissionCategoryColor(school.admissionCategory) }}
                    >
                      {school.admissionCategory}
                    </div>
                  )}
                </div>
              </div>
              
              <div className="school-content">
                <h3 className="school-name">{school.name}</h3>
                <p className="school-location">
                  <MapPin size={16} />
                  {school.location}
                </p>
                
                <div className="school-stats">
                  <div className="stat">
                    <DollarSign size={16} />
                    <span>${school.tuition.toLocaleString()}/year</span>
                  </div>
                  <div className="stat">
                    <TrendingUp size={16} />
                    <span>{school.acceptanceRate}% acceptance</span>
                  </div>
                  <div className="stat">
                    <Users size={16} />
                    <span>{school.studentPopulation.toLocaleString()} students</span>
                  </div>
                  <div className="stat">
                    <Star size={16} />
                    <span>GPA: {school.averageGPA}</span>
                  </div>
                </div>
                
                <div className="school-programs">
                  <h4>Strong Programs:</h4>
                  <div className="programs-list">
                    {school.strongPrograms.slice(0, 3).map((program, index) => (
                      <span key={index} className="program-tag">{program}</span>
                    ))}
                    {school.strongPrograms.length > 3 && (
                      <span className="program-tag">+{school.strongPrograms.length - 3} more</span>
                    )}
                  </div>
                </div>
                
                {school.topReasons && school.topReasons.length > 0 && (
                  <div className="top-reasons">
                    <h4>Why This School Matches:</h4>
                    <ul>
                      {school.topReasons.map((reason, index) => (
                        <li key={index}>{reason}</li>
                      ))}
                    </ul>
                  </div>
                )}
                
                {school.isTransferFriendly && (
                  <div className="transfer-friendly">
                    <span className="transfer-badge">Transfer-Friendly</span>
                  </div>
                )}
                
                <p className="school-description">{school.description}</p>
                
                <Link to={`/school/${school.id}`} className="btn btn-primary">
                  View Details
                </Link>
              </div>
            </div>
          ))}
        </div>
      </div>

      <style jsx="true">{`
        .results {
          min-height: 100vh;
          padding: 2rem 0;
          background: var(--bg-primary);
        }
        
        .results-header {
          max-width: 1200px;
          margin: 0 auto 3rem;
          padding: 0 2rem;
        }
        
        .results-intro h1 {
          font-size: 2.5rem;
          font-weight: 700;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }
        
        .results-intro p {
          font-size: 1.25rem;
          color: var(--text-secondary);
          margin-bottom: 2rem;
          line-height: 1.6;
        }
        
        .profile-summary {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          border-left: 4px solid var(--primary-color);
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .profile-summary h3 {
          margin-bottom: 1rem;
          color: var(--text-primary);
          font-weight: 600;
        }
        
        .profile-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 1.5rem;
        }
        
        .profile-item {
          color: var(--text-secondary);
          font-weight: 500;
        }
        
        .filters-section {
          max-width: 1200px;
          margin: 0 auto 3rem;
          padding: 0 2rem;
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .filters-header {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin-bottom: 1.5rem;
        }
        
        .filters-header h3 {
          margin: 0;
          color: var(--text-primary);
          font-weight: 600;
          font-size: 1.25rem;
        }
        
        .filters-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 1.5rem;
          margin-bottom: 1.5rem;
        }
        
        .filter-group {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }
        
        .filter-group label {
          font-weight: 600;
          color: var(--text-primary);
          font-size: 0.9rem;
        }
        
        .filter-group input {
          padding: 0.75rem 1rem;
          border: 2px solid var(--border-color);
          border-radius: 8px;
          font-size: 0.875rem;
          background: var(--bg-primary);
          color: var(--text-primary);
          transition: all 0.2s ease;
        }
        
        .filter-group input:focus {
          outline: none;
          border-color: var(--primary-color);
          box-shadow: 0 0 0 3px var(--primary-color-alpha);
        }
        
        .sort-options {
          display: flex;
          align-items: center;
          gap: 1rem;
        }
        
        .sort-options label {
          font-weight: 600;
          color: var(--text-primary);
        }
        
        .sort-options select {
          padding: 0.75rem 1rem;
          border: 2px solid var(--border-color);
          border-radius: 8px;
          background: var(--bg-primary);
          color: var(--text-primary);
          transition: all 0.2s ease;
        }
        
        .sort-options select:focus {
          outline: none;
          border-color: var(--primary-color);
          box-shadow: 0 0 0 3px var(--primary-color-alpha);
        }
        
        .results-count {
          margin-bottom: 2rem;
          color: var(--text-secondary);
          font-weight: 500;
        }
        
        .schools-grid {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 2rem;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
          gap: 2rem;
        }
        
        .school-card {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          overflow: hidden;
          box-shadow: 0 4px 6px var(--shadow-color);
          transition: all 0.3s ease;
        }
        
        .school-card:hover {
          transform: translateY(-8px);
          box-shadow: 0 20px 40px var(--shadow-color);
        }
        
        .school-header {
          position: relative;
          height: 200px;
        }
        
        .school-image {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        
        .match-score {
          position: absolute;
          top: 1rem;
          right: 1rem;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 0.25rem;
        }
        
        .score-circle {
          width: 50px;
          height: 50px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          color: white;
          font-weight: bold;
          font-size: 1.125rem;
        }
        
        .score-label {
          background: rgba(0, 0, 0, 0.7);
          color: white;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.75rem;
          font-weight: 500;
        }
        
        .admission-category {
          position: absolute;
          top: 0.5rem;
          right: 0.5rem;
          color: white;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.75rem;
          font-weight: 600;
          text-transform: uppercase;
        }
        
        .school-content {
          padding: 1.5rem;
        }
        
        .school-name {
          margin-bottom: 0.5rem;
          color: #1e293b;
        }
        
        .school-location {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: #64748b;
          margin-bottom: 1rem;
        }
        
        .school-stats {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 0.75rem;
          margin-bottom: 1.5rem;
        }
        
        .stat {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: #64748b;
          font-size: 0.875rem;
        }
        
        .school-programs {
          margin-bottom: 1rem;
        }
        
        .school-programs h4 {
          margin-bottom: 0.5rem;
          color: #1e293b;
          font-size: 1rem;
        }
        
        .programs-list {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }
        
        .program-tag {
          background: #e0f2fe;
          color: #0369a1;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.75rem;
          font-weight: 500;
        }
        
        .top-reasons {
          margin-bottom: 1rem;
        }
        
        .top-reasons h4 {
          margin-bottom: 0.5rem;
          color: #1e293b;
          font-size: 1rem;
        }
        
        .top-reasons ul {
          list-style: none;
          padding: 0;
        }
        
        .top-reasons li {
          padding: 0.25rem 0;
          color: #059669;
          font-size: 0.875rem;
          position: relative;
          padding-left: 1rem;
        }
        
        .top-reasons li:before {
          content: "✓";
          position: absolute;
          left: 0;
          color: #059669;
          font-weight: bold;
        }
        
        .transfer-friendly {
          margin-bottom: 1rem;
        }
        
        .transfer-badge {
          background: #fef3c7;
          color: #92400e;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.75rem;
          font-weight: 600;
        }
        
        .school-description {
          color: #64748b;
          font-size: 0.875rem;
          line-height: 1.5;
          margin-bottom: 1.5rem;
        }
        
        .no-results {
          text-align: center;
          padding: 4rem 2rem;
        }
        
        .no-results h2 {
          margin-bottom: 1rem;
          color: #1e293b;
        }
        
        .no-results p {
          color: #64748b;
          margin-bottom: 2rem;
        }
        
        @media (max-width: 768px) {
          .results {
            padding: 1rem 0;
          }
          
          .results-header {
            padding: 0 1rem;
          }
          
          .results-intro h1 {
            font-size: 2rem;
          }
          
          .filters-section {
            margin: 0 1rem 2rem;
            padding: 1.5rem;
          }
          
          .filters-grid {
            grid-template-columns: 1fr;
            gap: 1rem;
          }
          
          .schools-grid {
            padding: 0 1rem;
            grid-template-columns: 1fr;
            gap: 1.5rem;
          }
          
          .school-stats {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};

export default Results; 