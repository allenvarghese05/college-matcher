import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { Star, MapPin, Users, DollarSign, TrendingUp, Home, Calendar, Users as UsersIcon, MessageCircle, ThumbsUp, ThumbsDown } from 'lucide-react';
import { useTheme } from '../App';
import axios from 'axios';

const SchoolProfile = () => {
  const { id } = useParams();
  const { isDarkMode } = useTheme();
  const [school, setSchool] = useState(null);
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const [newReview, setNewReview] = useState({
    title: '',
    content: '',
    rating: 5,
    major: '',
    year: '',
    pros: '',
    cons: ''
  });

  useEffect(() => {
    fetchSchoolData();
  }, [id]);

  const fetchSchoolData = async () => {
    try {
      const [schoolResponse, reviewsResponse] = await Promise.all([
        axios.get(`/api/schools/${id}`),
        axios.get(`/api/reviews/${id}`)
      ]);
      
      setSchool(schoolResponse.data.school);
      setReviews(reviewsResponse.data.reviews);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching school data:', error);
      setLoading(false);
    }
  };

  const handleReviewSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await axios.post('/api/reviews', {
        ...newReview,
        schoolId: id,
        pros: newReview.pros.split(',').map(p => p.trim()).filter(p => p),
        cons: newReview.cons.split(',').map(c => c.trim()).filter(c => c)
      });
      
      setReviews([...reviews, response.data.review]);
      setNewReview({
        title: '',
        content: '',
        rating: 5,
        major: '',
        year: '',
        pros: '',
        cons: ''
      });
      
      alert('Review submitted successfully!');
    } catch (error) {
      console.error('Error submitting review:', error);
      alert('Error submitting review. Please try again.');
    }
  };

  const renderStars = (rating) => {
    return Array.from({ length: 5 }, (_, i) => (
      <span key={i} className={`star ${i < rating ? '' : 'empty'}`}>
        ★
      </span>
    ));
  };

  const getAverageRating = () => {
    if (reviews.length === 0) return 0;
    const total = reviews.reduce((sum, review) => sum + review.rating, 0);
    return (total / reviews.length).toFixed(1);
  };

  if (loading) {
    return (
      <div className="loading">
        <div className="spinner"></div>
        <p>Loading school information...</p>
      </div>
    );
  }

  if (!school) {
    return (
      <div className="error">
        <h2>School not found</h2>
        <p>The school you're looking for doesn't exist.</p>
      </div>
    );
  }

  return (
    <div className="school-profile">
      {/* Hero Section */}
      <div className="hero-section">
        <img 
          src={school.image} 
          alt={school.name}
          className="hero-image"
          onError={(e) => {
            e.target.src = 'https://images.unsplash.com/photo-1523050854058-8df90110c9d1?w=400';
          }}
        />
        <div className="hero-overlay">
          <div className="hero-content">
            <h1>{school.name}</h1>
            <p className="location">
              <MapPin size={20} />
              {school.location}
            </p>
            <div className="hero-stats">
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
      </div>

      {/* Navigation Tabs */}
      <div className="tabs">
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
          className={`tab ${activeTab === 'campus' ? 'active' : ''}`}
          onClick={() => setActiveTab('campus')}
        >
          Campus Life
        </button>
        <button 
          className={`tab ${activeTab === 'reviews' ? 'active' : ''}`}
          onClick={() => setActiveTab('reviews')}
        >
          Reviews ({reviews.length})
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'overview' && (
          <div className="overview-tab">
            <div className="overview-grid">
              <div className="overview-card">
                <h3>About {school.name}</h3>
                <p>{school.description}</p>
              </div>
              
              <div className="overview-card">
                <h3>Quick Facts</h3>
                <div className="facts-list">
                  <div className="fact">
                    <strong>Tuition:</strong> ${school.tuition.toLocaleString()}/year
                  </div>
                  <div className="fact">
                    <strong>Acceptance Rate:</strong> {school.acceptanceRate}%
                  </div>
                  <div className="fact">
                    <strong>Student Population:</strong> {school.studentPopulation.toLocaleString()}
                  </div>
                  <div className="fact">
                    <strong>Average GPA:</strong> {school.averageGPA}
                  </div>
                  <div className="fact">
                    <strong>International Students:</strong> {school.demographics.internationalStudents}%
                  </div>
                  <div className="fact">
                    <strong>Diversity Index:</strong> {school.demographics.diversityIndex}/100
                  </div>
                </div>
              </div>
              
              <div className="overview-card">
                <h3>Strong Programs</h3>
                <div className="programs-grid">
                  {school.strongPrograms.map((program, index) => (
                    <span key={index} className="program-tag">{program}</span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'academics' && (
          <div className="academics-tab">
            <div className="academics-grid">
              <div className="academics-card">
                <h3>Academic Structure</h3>
                <div className="academic-info">
                  <div className="info-item">
                    <Calendar size={20} />
                    <div>
                      <strong>Academic Calendar:</strong>
                      <p>{school.scheduling.quarterSystem ? 'Quarter System' : 'Semester System'}</p>
                    </div>
                  </div>
                  <div className="info-item">
                    <UsersIcon size={20} />
                    <div>
                      <strong>Class Size:</strong>
                      <p>{school.scheduling.classSize}</p>
                    </div>
                  </div>
                  <div className="info-item">
                    <TrendingUp size={20} />
                    <div>
                      <strong>Schedule Flexibility:</strong>
                      <p>{school.scheduling.flexibility}</p>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="academics-card">
                <h3>Programs & Majors</h3>
                <div className="programs-list">
                  {school.strongPrograms.map((program, index) => (
                    <div key={index} className="program-item">
                      <span className="program-name">{program}</span>
                      <span className="program-status">Strong Program</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'campus' && (
          <div className="campus-tab">
            <div className="campus-grid">
              <div className="campus-card">
                <h3>Housing Information</h3>
                <div className="housing-info">
                  <div className="info-item">
                    <Home size={20} />
                    <div>
                      <strong>On-Campus Housing:</strong>
                      <p>{school.housing.onCampus ? 'Available' : 'Not Available'}</p>
                    </div>
                  </div>
                  <div className="info-item">
                    <DollarSign size={20} />
                    <div>
                      <strong>Average Housing Cost:</strong>
                      <p>${school.housing.averageCost.toLocaleString()}/year</p>
                    </div>
                  </div>
                  <div className="info-item">
                    <strong>Housing Options:</strong>
                    <div className="options-list">
                      {school.housing.options.map((option, index) => (
                        <span key={index} className="option-tag">{option}</span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="campus-card">
                <h3>Student Demographics</h3>
                <div className="demographics-info">
                  <div className="demo-item">
                    <strong>Gender Ratio:</strong> {school.demographics.genderRatio}
                  </div>
                  <div className="demo-item">
                    <strong>International Students:</strong> {school.demographics.internationalStudents}%
                  </div>
                  <div className="demo-item">
                    <strong>Diversity Index:</strong> {school.demographics.diversityIndex}/100
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'reviews' && (
          <div className="reviews-tab">
            <div className="reviews-header">
              <div className="reviews-summary">
                <h3>Student Reviews</h3>
                <div className="rating-summary">
                  <div className="average-rating">
                    <span className="rating-number">{getAverageRating()}</span>
                    <div className="stars">{renderStars(Math.round(getAverageRating()))}</div>
                    <span className="review-count">({reviews.length} reviews)</span>
                  </div>
                </div>
              </div>
              
              <button 
                className="btn btn-primary"
                onClick={() => document.getElementById('review-form').scrollIntoView()}
              >
                Write a Review
              </button>
            </div>
            
            <div className="reviews-list">
              {reviews.length === 0 ? (
                <div className="no-reviews">
                  <MessageCircle size={48} />
                  <h4>No reviews yet</h4>
                  <p>Be the first to share your experience at {school.name}!</p>
                </div>
              ) : (
                reviews.map((review) => (
                  <div key={review.id} className="review-card">
                    <div className="review-header">
                      <div className="reviewer-info">
                        <h4>{review.title}</h4>
                        <p className="reviewer-details">
                          {review.studentName} • {review.major} • {review.year}
                        </p>
                      </div>
                      <div className="review-rating">
                        <div className="stars">{renderStars(review.rating)}</div>
                        <span className="rating-text">{review.rating}/5</span>
                      </div>
                    </div>
                    
                    <p className="review-content">{review.content}</p>
                    
                    {review.pros.length > 0 && (
                      <div className="review-pros-cons">
                        <div className="pros">
                          <h5>Pros:</h5>
                          <ul>
                            {review.pros.map((pro, index) => (
                              <li key={index}>{pro}</li>
                            ))}
                          </ul>
                        </div>
                        {review.cons.length > 0 && (
                          <div className="cons">
                            <h5>Cons:</h5>
                            <ul>
                              {review.cons.map((con, index) => (
                                <li key={index}>{con}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                    
                    <div className="review-footer">
                      <span className="review-date">
                        {new Date(review.timestamp).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
            
            {/* Review Form */}
            <div id="review-form" className="review-form-section">
              <h3>Write a Review</h3>
              <form onSubmit={handleReviewSubmit} className="review-form">
                <div className="form-grid">
                  <div className="form-group">
                    <label>Review Title</label>
                    <input
                      type="text"
                      value={newReview.title}
                      onChange={(e) => setNewReview({...newReview, title: e.target.value})}
                      required
                    />
                  </div>
                  
                  <div className="form-group">
                    <label>Your Major</label>
                    <input
                      type="text"
                      value={newReview.major}
                      onChange={(e) => setNewReview({...newReview, major: e.target.value})}
                      required
                    />
                  </div>
                  
                  <div className="form-group">
                    <label>Year</label>
                    <select
                      value={newReview.year}
                      onChange={(e) => setNewReview({...newReview, year: e.target.value})}
                      required
                    >
                      <option value="">Select year</option>
                      <option value="Freshman">Freshman</option>
                      <option value="Sophomore">Sophomore</option>
                      <option value="Junior">Junior</option>
                      <option value="Senior">Senior</option>
                      <option value="Graduate">Graduate</option>
                      <option value="Alumni">Alumni</option>
                    </select>
                  </div>
                  
                  <div className="form-group">
                    <label>Rating</label>
                    <select
                      value={newReview.rating}
                      onChange={(e) => setNewReview({...newReview, rating: parseInt(e.target.value)})}
                      required
                    >
                      <option value="5">5 - Excellent</option>
                      <option value="4">4 - Very Good</option>
                      <option value="3">3 - Good</option>
                      <option value="2">2 - Fair</option>
                      <option value="1">1 - Poor</option>
                    </select>
                  </div>
                </div>
                
                <div className="form-group">
                  <label>Your Review</label>
                  <textarea
                    value={newReview.content}
                    onChange={(e) => setNewReview({...newReview, content: e.target.value})}
                    required
                    rows="4"
                  />
                </div>
                
                <div className="form-grid">
                  <div className="form-group">
                    <label>Pros (comma-separated)</label>
                    <input
                      type="text"
                      value={newReview.pros}
                      onChange={(e) => setNewReview({...newReview, pros: e.target.value})}
                      placeholder="e.g., Great professors, Beautiful campus, Strong community"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label>Cons (comma-separated)</label>
                    <input
                      type="text"
                      value={newReview.cons}
                      onChange={(e) => setNewReview({...newReview, cons: e.target.value})}
                      placeholder="e.g., Expensive, Large class sizes, Limited parking"
                    />
                  </div>
                </div>
                
                <button type="submit" className="btn btn-primary">
                  Submit Review
                </button>
              </form>
            </div>
          </div>
        )}
      </div>

      <style jsx>{`
        .school-profile {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0;
        }
        
        .hero-section {
          position: relative;
          height: 400px;
          border-radius: 1rem;
          overflow: hidden;
          margin-bottom: 2rem;
        }
        
        .hero-image {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        
        .hero-overlay {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: linear-gradient(135deg, rgba(0,0,0,0.7) 0%, rgba(0,0,0,0.3) 100%);
          display: flex;
          align-items: center;
          padding: 2rem;
        }
        
        .hero-content h1 {
          color: white;
          margin-bottom: 1rem;
          font-size: 2.5rem;
        }
        
        .location {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: white;
          margin-bottom: 1.5rem;
          font-size: 1.125rem;
        }
        
        .hero-stats {
          display: flex;
          gap: 2rem;
          flex-wrap: wrap;
        }
        
        .hero-stats .stat {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: white;
          background: rgba(255, 255, 255, 0.1);
          padding: 0.5rem 1rem;
          border-radius: 0.5rem;
        }
        
        .tabs {
          display: flex;
          background: white;
          border-radius: 1rem;
          padding: 0.5rem;
          margin-bottom: 2rem;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        
        .tab {
          flex: 1;
          padding: 1rem;
          border: none;
          background: transparent;
          border-radius: 0.5rem;
          cursor: pointer;
          font-weight: 500;
          transition: all 0.2s ease;
        }
        
        .tab:hover {
          background: #f1f5f9;
        }
        
        .tab.active {
          background: #3b82f6;
          color: white;
        }
        
        .tab-content {
          background: white;
          border-radius: 1rem;
          padding: 2rem;
          box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }
        
        .overview-grid,
        .academics-grid,
        .campus-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 2rem;
        }
        
        .overview-card,
        .academics-card,
        .campus-card {
          background: #f8fafc;
          border-radius: 0.5rem;
          padding: 1.5rem;
        }
        
        .overview-card h3,
        .academics-card h3,
        .campus-card h3 {
          margin-bottom: 1rem;
          color: #1e293b;
        }
        
        .facts-list,
        .demographics-info {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }
        
        .fact,
        .demo-item {
          color: #64748b;
        }
        
        .programs-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }
        
        .program-tag {
          background: #e0f2fe;
          color: #0369a1;
          padding: 0.25rem 0.75rem;
          border-radius: 1rem;
          font-size: 0.875rem;
          font-weight: 500;
        }
        
        .academic-info,
        .housing-info {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }
        
        .info-item {
          display: flex;
          align-items: flex-start;
          gap: 1rem;
        }
        
        .info-item > div {
          flex: 1;
        }
        
        .info-item strong {
          display: block;
          margin-bottom: 0.25rem;
          color: #1e293b;
        }
        
        .info-item p {
          margin: 0;
          color: #64748b;
        }
        
        .options-list {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
          margin-top: 0.5rem;
        }
        
        .option-tag {
          background: #f1f5f9;
          color: #475569;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.875rem;
        }
        
        .programs-list {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }
        
        .program-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 0.75rem;
          background: white;
          border-radius: 0.5rem;
        }
        
        .program-name {
          font-weight: 500;
          color: #1e293b;
        }
        
        .program-status {
          background: #dcfce7;
          color: #166534;
          padding: 0.25rem 0.5rem;
          border-radius: 0.25rem;
          font-size: 0.75rem;
          font-weight: 500;
        }
        
        .reviews-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 2rem;
          padding-bottom: 1rem;
          border-bottom: 1px solid #e2e8f0;
        }
        
        .rating-summary {
          display: flex;
          align-items: center;
          gap: 1rem;
        }
        
        .average-rating {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        
        .rating-number {
          font-size: 2rem;
          font-weight: bold;
          color: #1e293b;
        }
        
        .review-count {
          color: #64748b;
        }
        
        .reviews-list {
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
          margin-bottom: 3rem;
        }
        
        .review-card {
          background: #f8fafc;
          border-radius: 0.5rem;
          padding: 1.5rem;
          border-left: 4px solid #3b82f6;
        }
        
        .review-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 1rem;
        }
        
        .reviewer-info h4 {
          margin-bottom: 0.25rem;
          color: #1e293b;
        }
        
        .reviewer-details {
          color: #64748b;
          font-size: 0.875rem;
        }
        
        .review-rating {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        
        .rating-text {
          color: #64748b;
          font-size: 0.875rem;
        }
        
        .review-content {
          color: #374151;
          line-height: 1.6;
          margin-bottom: 1rem;
        }
        
        .review-pros-cons {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 1rem;
          margin-bottom: 1rem;
        }
        
        .pros h5,
        .cons h5 {
          margin-bottom: 0.5rem;
          color: #1e293b;
        }
        
        .pros ul,
        .cons ul {
          list-style: none;
          padding: 0;
          margin: 0;
        }
        
        .pros li,
        .cons li {
          padding: 0.25rem 0;
          color: #64748b;
          font-size: 0.875rem;
        }
        
        .pros li::before {
          content: "✓ ";
          color: #10b981;
          font-weight: bold;
        }
        
        .cons li::before {
          content: "✗ ";
          color: #ef4444;
          font-weight: bold;
        }
        
        .review-footer {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding-top: 1rem;
          border-top: 1px solid #e2e8f0;
        }
        
        .review-date {
          color: #64748b;
          font-size: 0.875rem;
        }
        
        .no-reviews {
          text-align: center;
          padding: 3rem;
          color: #64748b;
        }
        
        .no-reviews h4 {
          margin: 1rem 0 0.5rem;
          color: #1e293b;
        }
        
        .review-form-section {
          background: #f8fafc;
          border-radius: 0.5rem;
          padding: 2rem;
          margin-top: 2rem;
        }
        
        .review-form-section h3 {
          margin-bottom: 1.5rem;
          color: #1e293b;
        }
        
        .review-form {
          display: flex;
          flex-direction: column;
          gap: 1.5rem;
        }
        
        .form-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1rem;
        }
        
        .form-group {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }
        
        .form-group label {
          font-weight: 500;
          color: #374151;
        }
        
        .form-group input,
        .form-group select,
        .form-group textarea {
          padding: 0.75rem;
          border: 2px solid #e2e8f0;
          border-radius: 0.5rem;
          font-size: 1rem;
        }
        
        .form-group input:focus,
        .form-group select:focus,
        .form-group textarea:focus {
          outline: none;
          border-color: #3b82f6;
        }
        
        @media (max-width: 768px) {
          .hero-section {
            height: 300px;
          }
          
          .hero-content h1 {
            font-size: 2rem;
          }
          
          .hero-stats {
            flex-direction: column;
            gap: 1rem;
          }
          
          .tabs {
            flex-direction: column;
          }
          
          .tab-content {
            padding: 1.5rem;
          }
          
          .overview-grid,
          .academics-grid,
          .campus-grid {
            grid-template-columns: 1fr;
          }
          
          .reviews-header {
            flex-direction: column;
            gap: 1rem;
            align-items: flex-start;
          }
          
          .review-pros-cons {
            grid-template-columns: 1fr;
          }
          
          .form-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};

export default SchoolProfile; 