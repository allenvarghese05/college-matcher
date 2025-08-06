import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Star, MapPin, Users, DollarSign, TrendingUp, Filter, Search } from 'lucide-react';
import { useTheme } from '../App';
import axios from 'axios';

const BrowseSchools = () => {
  const { isDarkMode } = useTheme();
  const [schools, setSchools] = useState([]);
  const [filteredSchools, setFilteredSchools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    location: '',
    maxCost: '',
    minGPA: '',
    maxAcceptanceRate: '',
    minPopulation: '',
    maxPopulation: '',
    search: ''
  });
  const [sortBy, setSortBy] = useState('name');

  useEffect(() => {
    fetchSchools();
  }, []);

  const fetchSchools = async () => {
    try {
      const response = await axios.get('/api/schools');
      setSchools(response.data.schools);
      setFilteredSchools(response.data.schools);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching schools:', error);
      setLoading(false);
    }
  };

  useEffect(() => {
    let filtered = [...schools];
    
    // Search filter
    if (filters.search) {
      filtered = filtered.filter(school => 
        school.name.toLowerCase().includes(filters.search.toLowerCase()) ||
        school.location.toLowerCase().includes(filters.search.toLowerCase()) ||
        school.strongPrograms.some(program => 
          program.toLowerCase().includes(filters.search.toLowerCase())
        )
      );
    }
    
    // Location filter
    if (filters.location) {
      filtered = filtered.filter(school => 
        school.location.toLowerCase().includes(filters.location.toLowerCase())
      );
    }
    
    // Cost filter
    if (filters.maxCost) {
      filtered = filtered.filter(school => 
        school.tuition <= parseInt(filters.maxCost)
      );
    }
    
    // GPA filter
    if (filters.minGPA) {
      filtered = filtered.filter(school => 
        school.averageGPA >= parseFloat(filters.minGPA)
      );
    }
    
    // Acceptance rate filter
    if (filters.maxAcceptanceRate) {
      filtered = filtered.filter(school => 
        school.acceptanceRate <= parseInt(filters.maxAcceptanceRate)
      );
    }
    
    // Population filters
    if (filters.minPopulation) {
      filtered = filtered.filter(school => 
        school.studentPopulation >= parseInt(filters.minPopulation)
      );
    }
    
    if (filters.maxPopulation) {
      filtered = filtered.filter(school => 
        school.studentPopulation <= parseInt(filters.maxPopulation)
      );
    }
    
    setFilteredSchools(filtered);
  }, [filters, schools]);

  const handleFilterChange = (field, value) => {
    setFilters(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleSort = (field) => {
    setSortBy(field);
    const sorted = [...filteredSchools].sort((a, b) => {
      if (field === 'name') {
        return a.name.localeCompare(b.name);
      } else if (field === 'tuition') {
        return a.tuition - b.tuition;
      } else if (field === 'acceptanceRate') {
        return a.acceptanceRate - b.acceptanceRate;
      } else if (field === 'averageGPA') {
        return b.averageGPA - a.averageGPA;
      } else if (field === 'studentPopulation') {
        return b.studentPopulation - a.studentPopulation;
      }
      return 0;
    });
    setFilteredSchools(sorted);
  };

  const clearFilters = () => {
    setFilters({
      location: '',
      maxCost: '',
      minGPA: '',
      maxAcceptanceRate: '',
      minPopulation: '',
      maxPopulation: '',
      search: ''
    });
    setSortBy('name');
  };

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner"></div>
        <p>Loading schools...</p>
      </div>
    );
  }

  return (
    <div className="browse-schools">
      <div className="browse-header">
        <h1>Browse All Schools</h1>
        <p>Explore colleges and universities to find your perfect match</p>
      </div>

      {/* Search and Filters */}
      <div className="filters-section">
        <div className="search-bar">
          <Search size={20} />
          <input
            type="text"
            placeholder="Search schools, locations, or programs..."
            value={filters.search}
            onChange={(e) => handleFilterChange('search', e.target.value)}
          />
        </div>

        <div className="filters-header">
          <Filter size={20} />
          <h3>Filters</h3>
          <button onClick={clearFilters} className="btn btn-outline btn-small">
            Clear All
          </button>
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
            <option value="name">Name (A-Z)</option>
            <option value="tuition">Tuition (Low to High)</option>
            <option value="acceptanceRate">Acceptance Rate (Low to High)</option>
            <option value="averageGPA">Average GPA (High to Low)</option>
            <option value="studentPopulation">Student Population (High to Low)</option>
          </select>
        </div>
      </div>

      {/* Results */}
      <div className="results-content">
        <div className="results-count">
          <p>Showing {filteredSchools.length} of {schools.length} schools</p>
        </div>
        
        {filteredSchools.length === 0 ? (
          <div className="no-results">
            <h3>No schools found</h3>
            <p>Try adjusting your search criteria or filters.</p>
          </div>
        ) : (
          <div className="schools-grid">
            {filteredSchools.map((school) => (
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
                  
                  <p className="school-description">{school.description}</p>
                  
                  <Link to={`/school/${school.id}`} className="btn btn-primary">
                    View Details
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <style jsx="true">{`
        .browse-schools {
          min-height: 100vh;
          padding: 2rem 0;
          background: var(--bg-primary);
        }
        
        .browse-header {
          text-align: center;
          margin-bottom: 3rem;
          max-width: 1200px;
          margin-left: auto;
          margin-right: auto;
          padding: 0 2rem;
        }
        
        .browse-header h1 {
          font-size: 2.5rem;
          font-weight: 700;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }
        
        .browse-header p {
          font-size: 1.25rem;
          color: var(--text-secondary);
          line-height: 1.6;
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
        
        .search-bar {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          background: var(--bg-secondary);
          border: 2px solid var(--border-color);
          border-radius: 12px;
          padding: 1rem 1.25rem;
          margin-bottom: 2rem;
          transition: all 0.2s ease;
        }
        
        .search-bar:focus-within {
          border-color: var(--primary-color);
          box-shadow: 0 0 0 3px var(--primary-color-alpha);
        }
        
        .search-bar input {
          flex: 1;
          border: none;
          background: transparent;
          font-size: 1rem;
          outline: none;
          color: var(--text-primary);
        }
        
        .search-bar input::placeholder {
          color: var(--text-secondary);
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
          flex: 1;
          font-weight: 600;
          font-size: 1.25rem;
        }
        
        .btn-small {
          padding: 0.5rem 1rem;
          font-size: 0.875rem;
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
        
        .no-results {
          text-align: center;
          padding: 4rem 2rem;
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .no-results h3 {
          margin-bottom: 1rem;
          color: var(--text-primary);
          font-weight: 600;
        }
        
        .no-results p {
          color: var(--text-secondary);
        }
        
        .schools-grid {
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
          height: 200px;
        }
        
        .school-image {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        
        .school-content {
          padding: 1.5rem;
        }
        
        .school-name {
          margin-bottom: 0.5rem;
          color: var(--text-primary);
          font-weight: 600;
          font-size: 1.25rem;
        }
        
        .school-location {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: var(--text-secondary);
          margin-bottom: 1rem;
          font-weight: 500;
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
          color: var(--text-secondary);
          font-size: 0.875rem;
          font-weight: 500;
        }
        
        .school-programs {
          margin-bottom: 1rem;
        }
        
        .school-programs h4 {
          margin-bottom: 0.5rem;
          color: var(--text-primary);
          font-size: 1rem;
          font-weight: 600;
        }
        
        .programs-list {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }
        
        .program-tag {
          background: var(--primary-color-alpha);
          color: var(--primary-color);
          padding: 0.25rem 0.75rem;
          border-radius: 20px;
          font-size: 0.75rem;
          font-weight: 500;
        }
        
        .school-description {
          color: var(--text-secondary);
          font-size: 0.875rem;
          line-height: 1.6;
          margin-bottom: 1.5rem;
        }
        
        @media (max-width: 768px) {
          .browse-schools {
            padding: 1rem 0;
          }
          
          .browse-header {
            padding: 0 1rem;
          }
          
          .browse-header h1 {
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
          
          .results-content {
            padding: 0 1rem;
          }
          
          .schools-grid {
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

export default BrowseSchools; 