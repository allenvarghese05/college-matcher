import React, { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { 
  MapPin, Users, DollarSign, TrendingUp, Star, Calendar, 
  BookOpen, GraduationCap, Home, ExternalLink, Heart, 
  MessageCircle, Share2, Download, Edit3, CheckCircle
} from 'lucide-react';
import { useTheme } from '../App';
import axios from 'axios';

const SchoolDetail = () => {
  const { id } = useParams();
  const { isDarkMode } = useTheme();
  const [school, setSchool] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [userNotes, setUserNotes] = useState('');
  const [isFavorite, setIsFavorite] = useState(false);
  const [applicationStatus, setApplicationStatus] = useState('not-started');
  const [applicationDeadline, setApplicationDeadline] = useState('');

  useEffect(() => {
    fetchSchoolData();
    fetchReviews();
  }, [id]);

  const fetchSchoolData = async () => {
    try {
      const response = await axios.get(`/api/schools/${id}`);
      setSchool(response.data.school);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching school data:', error);
      setLoading(false);
    }
  };

  const fetchReviews = async () => {
    try {
      const response = await axios.get(`/api/reviews/${id}`);
      setReviews(response.data.reviews);
    } catch (error) {
      console.error('Error fetching reviews:', error);
    }
  };

  const handleAddToFavorites = () => {
    setIsFavorite(!isFavorite);
    // Here you would typically save to user's favorites
  };

  const handleSaveNotes = () => {
    // Here you would typically save notes to user's account
    console.log('Saving notes:', userNotes);
  };

  const handleApplicationStatusChange = (status) => {
    setApplicationStatus(status);
    // Here you would typically save to user's application tracking
  };

  const handleExportData = () => {
    const data = {
      school: school,
      notes: userNotes,
      applicationStatus: applicationStatus,
      applicationDeadline: applicationDeadline,
      isFavorite: isFavorite
    };
    
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${school.name.replace(/\s+/g, '_')}_data.json`;
    a.click();
  };

  if (loading) {
    return (
      <div className="school-detail">
        <div className="loading">Loading school information...</div>
      </div>
    );
  }

  if (!school) {
    return (
      <div className="school-detail">
        <div className="error">School not found</div>
      </div>
    );
  }

  return (
    <div className="school-detail">
      {/* Header Section */}
      <div className="school-header">
        <div className="school-header-content">
          <div className="school-basic-info">
            <img 
              src={school.image} 
              alt={school.name}
              className="school-image"
              onError={(e) => {
                e.target.src = 'https://images.unsplash.com/photo-1523050854058-8df90110c9d1?w=400';
              }}
            />
            <div className="school-info">
              <h1 className="school-name">{school.name}</h1>
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
            </div>
          </div>
          
          <div className="school-actions">
            <button 
              className={`btn ${isFavorite ? 'btn-primary' : 'btn-secondary'}`}
              onClick={handleAddToFavorites}
            >
              <Heart size={16} />
              {isFavorite ? 'Favorited' : 'Add to Favorites'}
            </button>
            <button className="btn btn-secondary" onClick={handleExportData}>
              <Download size={16} />
              Export Data
            </button>
            <button className="btn btn-secondary">
              <Share2 size={16} />
              Share
            </button>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="school-tabs">
        <button 
          className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          Overview
        </button>
        <button 
          className={`tab ${activeTab === 'academics' ? 'active' : ''}`}
          onClick={() => setActiveTab('academics')}
        >
          Academics
        </button>
        <button 
          className={`tab ${activeTab === 'campus-life' ? 'active' : ''}`}
          onClick={() => setActiveTab('campus-life')}
        >
          Campus Life
        </button>
        <button 
          className={`tab ${activeTab === 'reviews' ? 'active' : ''}`}
          onClick={() => setActiveTab('reviews')}
        >
          Student Reviews
        </button>
        <button 
          className={`tab ${activeTab === 'application' ? 'active' : ''}`}
          onClick={() => setActiveTab('application')}
        >
          Application
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'overview' && (
          <div className="overview-tab">
            <div className="overview-grid">
              <div className="overview-section">
                <h3>About {school.name}</h3>
                <p>{school.description}</p>
                
                <div className="quick-facts">
                  <h4>Quick Facts</h4>
                  <div className="facts-grid">
                    <div className="fact">
                      <strong>Founded:</strong> 1868
                    </div>
                    <div className="fact">
                      <strong>Type:</strong> {school.tuition > 45000 ? 'Private' : 'Public'}
                    </div>
                    <div className="fact">
                      <strong>Setting:</strong> Urban
                    </div>
                    <div className="fact">
                      <strong>Endowment:</strong> $25.4B
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="overview-section">
                <h3>Official Links</h3>
                <div className="official-links">
                  <a href="#" className="link-item">
                    <ExternalLink size={16} />
                    Official Website
                  </a>
                  <a href="#" className="link-item">
                    <BookOpen size={16} />
                    Academic Programs
                  </a>
                  <a href="#" className="link-item">
                    <Home size={16} />
                    Virtual Campus Tour
                  </a>
                  <a href="#" className="link-item">
                    <GraduationCap size={16} />
                    Admissions Office
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'academics' && (
          <div className="academics-tab">
            <div className="academics-grid">
              <div className="academics-section">
                <h3>Strong Programs</h3>
                <div className="programs-list">
                  {school.strongPrograms.map((program, index) => (
                    <div key={index} className="program-item">
                      <h4>{program}</h4>
                      <p>Ranked #1 in the nation for this program</p>
                      <a href="#" className="program-link">View Program Details</a>
                    </div>
                  ))}
                </div>
              </div>
              
              <div className="academics-section">
                <h3>Academic Statistics</h3>
                <div className="academic-stats">
                  <div className="stat-item">
                    <strong>Student-Faculty Ratio:</strong> 6:1
                  </div>
                  <div className="stat-item">
                    <strong>Average Class Size:</strong> 15 students
                  </div>
                  <div className="stat-item">
                    <strong>Graduation Rate:</strong> 96%
                  </div>
                  <div className="stat-item">
                    <strong>Retention Rate:</strong> 98%
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'campus-life' && (
          <div className="campus-life-tab">
            <div className="campus-grid">
              <div className="campus-section">
                <h3>Housing</h3>
                <div className="housing-info">
                  <p><strong>On-campus housing:</strong> Available for all students</p>
                  <p><strong>Housing cost:</strong> $15,000/year</p>
                  <p><strong>Dining plans:</strong> Required for freshmen</p>
                </div>
              </div>
              
              <div className="campus-section">
                <h3>Student Demographics</h3>
                <div className="demographics">
                  <div className="demo-item">
                    <strong>Undergraduate:</strong> 7,000 students
                  </div>
                  <div className="demo-item">
                    <strong>Graduate:</strong> 3,000 students
                  </div>
                  <div className="demo-item">
                    <strong>International:</strong> 15%
                  </div>
                  <div className="demo-item">
                    <strong>Diversity:</strong> 45% students of color
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'reviews' && (
          <div className="reviews-tab">
            <div className="reviews-header">
              <h3>Student Reviews</h3>
              <button className="btn btn-primary">Write a Review</button>
            </div>
            
            <div className="reviews-list">
              {reviews.map((review) => (
                <div key={review.id} className="review-card">
                  <div className="review-header">
                    <div className="reviewer-info">
                      <strong>{review.studentName}</strong>
                      <span>{review.major} • Class of {review.year}</span>
                    </div>
                    <div className="review-rating">
                      {[...Array(5)].map((_, i) => (
                        <Star 
                          key={i} 
                          size={16} 
                          fill={i < review.rating ? '#fbbf24' : 'none'}
                          color="#fbbf24"
                        />
                      ))}
                    </div>
                  </div>
                  <h4>{review.title}</h4>
                  <p>{review.content}</p>
                  <div className="review-pros-cons">
                    <div className="pros">
                      <strong>Pros:</strong> {review.pros}
                    </div>
                    <div className="cons">
                      <strong>Cons:</strong> {review.cons}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === 'application' && (
          <div className="application-tab">
            <div className="application-grid">
              <div className="application-section">
                <h3>Application Tracking</h3>
                <div className="application-status">
                  <label>Application Status:</label>
                  <select 
                    value={applicationStatus} 
                    onChange={(e) => handleApplicationStatusChange(e.target.value)}
                  >
                    <option value="not-started">Not Started</option>
                    <option value="in-progress">In Progress</option>
                    <option value="submitted">Submitted</option>
                    <option value="accepted">Accepted</option>
                    <option value="rejected">Rejected</option>
                    <option value="waitlisted">Waitlisted</option>
                  </select>
                </div>
                
                <div className="application-deadline">
                  <label>Application Deadline:</label>
                  <input 
                    type="date" 
                    value={applicationDeadline}
                    onChange={(e) => setApplicationDeadline(e.target.value)}
                  />
                </div>
                
                <div className="application-requirements">
                  <h4>Application Requirements</h4>
                  <ul>
                    <li>Common App or Coalition App</li>
                    <li>Official high school transcript</li>
                    <li>SAT/ACT scores (optional for 2024)</li>
                    <li>2 letters of recommendation</li>
                    <li>Personal essay</li>
                    <li>Application fee: $75</li>
                  </ul>
                </div>
              </div>
              
              <div className="application-section">
                <h3>Personal Notes</h3>
                <textarea
                  value={userNotes}
                  onChange={(e) => setUserNotes(e.target.value)}
                  placeholder="Add your personal notes about this school..."
                  rows={6}
                />
                <button className="btn btn-primary" onClick={handleSaveNotes}>
                  <Edit3 size={16} />
                  Save Notes
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <style jsx>{`
        .school-detail {
          max-width: 1200px;
          margin: 0 auto;
          padding: 2rem 0;
        }
        
        .school-header {
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
          padding: 3rem 0;
          margin-bottom: 2rem;
        }
        
        .school-header-content {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          gap: 2rem;
        }
        
        .school-basic-info {
          display: flex;
          gap: 2rem;
          flex: 1;
        }
        
        .school-image {
          width: 120px;
          height: 120px;
          border-radius: 0.5rem;
          object-fit: cover;
        }
        
        .school-info {
          flex: 1;
        }
        
        .school-name {
          font-size: 2.5rem;
          margin-bottom: 0.5rem;
        }
        
        .school-location {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin-bottom: 1rem;
          opacity: 0.9;
        }
        
        .school-stats {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 1rem;
        }
        
        .stat {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          font-size: 0.875rem;
        }
        
        .school-actions {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }
        
        .school-tabs {
          display: flex;
          border-bottom: 1px solid #e5e7eb;
          margin-bottom: 2rem;
        }
        
        .tab {
          padding: 1rem 2rem;
          border: none;
          background: none;
          cursor: pointer;
          border-bottom: 2px solid transparent;
          color: #6b7280;
          font-weight: 500;
        }
        
        .tab.active {
          color: #3b82f6;
          border-bottom-color: #3b82f6;
        }
        
        .tab-content {
          min-height: 400px;
        }
        
        .overview-grid,
        .academics-grid,
        .campus-grid,
        .application-grid {
          display: grid;
          grid-template-columns: 2fr 1fr;
          gap: 2rem;
        }
        
        .overview-section,
        .academics-section,
        .campus-section,
        .application-section {
          background: white;
          padding: 2rem;
          border-radius: 0.5rem;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }
        
        .quick-facts {
          margin-top: 2rem;
        }
        
        .facts-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 1rem;
          margin-top: 1rem;
        }
        
        .fact {
          padding: 0.75rem;
          background: #f8fafc;
          border-radius: 0.25rem;
        }
        
        .official-links {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }
        
        .link-item {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.75rem;
          background: #f8fafc;
          border-radius: 0.25rem;
          text-decoration: none;
          color: #374151;
          transition: background-color 0.2s;
        }
        
        .link-item:hover {
          background: #e5e7eb;
        }
        
        .programs-list {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }
        
        .program-item {
          padding: 1rem;
          background: #f8fafc;
          border-radius: 0.25rem;
        }
        
        .program-item h4 {
          margin-bottom: 0.5rem;
          color: #1f2937;
        }
        
        .program-link {
          color: #3b82f6;
          text-decoration: none;
          font-size: 0.875rem;
        }
        
        .academic-stats,
        .demographics {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }
        
        .stat-item,
        .demo-item {
          padding: 0.75rem;
          background: #f8fafc;
          border-radius: 0.25rem;
        }
        
        .housing-info {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }
        
        .reviews-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 2rem;
        }
        
        .reviews-list {
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
        }
        
        .review-card {
          background: white;
          padding: 1.5rem;
          border-radius: 0.5rem;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
        }
        
        .review-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 1rem;
        }
        
        .reviewer-info {
          display: flex;
          flex-direction: column;
          gap: 0.25rem;
        }
        
        .reviewer-info span {
          font-size: 0.875rem;
          color: #6b7280;
        }
        
        .review-rating {
          display: flex;
          gap: 0.25rem;
        }
        
        .review-pros-cons {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
          margin-top: 1rem;
          padding-top: 1rem;
          border-top: 1px solid #e5e7eb;
        }
        
        .application-status,
        .application-deadline {
          margin-bottom: 1.5rem;
        }
        
        .application-status label,
        .application-deadline label {
          display: block;
          margin-bottom: 0.5rem;
          font-weight: 500;
        }
        
        .application-status select,
        .application-deadline input {
          width: 100%;
          padding: 0.75rem;
          border: 1px solid #d1d5db;
          border-radius: 0.25rem;
        }
        
        .application-requirements ul {
          list-style: none;
          padding: 0;
        }
        
        .application-requirements li {
          padding: 0.5rem 0;
          border-bottom: 1px solid #f3f4f6;
        }
        
        .application-requirements li:last-child {
          border-bottom: none;
        }
        
        textarea {
          width: 100%;
          padding: 0.75rem;
          border: 1px solid #d1d5db;
          border-radius: 0.25rem;
          resize: vertical;
          margin-bottom: 1rem;
        }
        
        .loading,
        .error {
          text-align: center;
          padding: 4rem 2rem;
          font-size: 1.125rem;
        }
        
        .error {
          color: #ef4444;
        }
        
        @media (max-width: 768px) {
          .school-header-content {
            flex-direction: column;
          }
          
          .school-basic-info {
            flex-direction: column;
            text-align: center;
          }
          
          .school-stats {
            grid-template-columns: 1fr;
          }
          
          .school-tabs {
            overflow-x: auto;
          }
          
          .overview-grid,
          .academics-grid,
          .campus-grid,
          .application-grid {
            grid-template-columns: 1fr;
          }
          
          .facts-grid {
            grid-template-columns: 1fr;
          }
          
          .review-pros-cons {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};

export default SchoolDetail; 