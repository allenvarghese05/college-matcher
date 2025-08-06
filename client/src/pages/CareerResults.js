import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, Brain, Briefcase, GraduationCap, TrendingUp, Target, CheckCircle } from 'lucide-react';
import { useTheme } from '../App';

const CareerResults = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { isDarkMode } = useTheme();
  const { careerResults, assessmentData } = location.state || {};

  if (!careerResults) {
    return (
      <div className="career-results">
        <div className="container">
          <h2>No Career Results Found</h2>
          <p>Please complete a career assessment first.</p>
          <button 
            className="btn btn-primary" 
            onClick={() => navigate('/career-assessment')}
          >
            Take Career Assessment
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="career-results">
      <div className="container">
        <div className="header">
          <button 
            className="btn btn-secondary" 
            onClick={() => navigate('/career-assessment')}
          >
            <ArrowLeft size={20} />
            Back to Assessment
          </button>
          <h1>Your Career Assessment Results</h1>
          <p>Based on your responses, here are your top career matches:</p>
        </div>

        <div className="results-grid">
          {Array.isArray(careerResults.topMatches) ? careerResults.topMatches.map((career, index) => (
            <div key={career.id} className="career-card">
              <div className="career-header">
                <div className="career-icon">
                  <Briefcase size={24} />
                </div>
                <div className="career-info">
                  <h3>{career.title}</h3>
                  <span className="category">{career.category}</span>
                  <div className="match-score">
                    <span className="score">{career.matchScore}%</span>
                    <span className="label">Match</span>
                  </div>
                </div>
              </div>
              
              <p className="description">{career.description}</p>
              
              <div className="career-details">
                <div className="detail-item">
                  <strong>Salary Range:</strong> ${career.salary_range.min.toLocaleString()} - ${career.salary_range.max.toLocaleString()}
                </div>
                <div className="detail-item">
                  <strong>Growth Outlook:</strong> {career.growth_outlook}
                </div>
                <div className="detail-item">
                  <strong>Education Required:</strong> {career.education_required}
                </div>
              </div>

              {career.explanation && (
                <div className="explanation">
                  <h4>Why This Career Fits You:</h4>
                  <p>{career.explanation}</p>
                </div>
              )}

              {career.skillsGap && (
                <div className="skills-gap">
                  <h4>Skills to Develop:</h4>
                  <ul>
                    {career.skillsGap.missingSkills.map((skill, idx) => (
                      <li key={idx}>{skill}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
                        )) : (
                <div className="no-results">
                  <p>No career matches found. Please try the assessment again.</p>
                </div>
              )}
        </div>

        {careerResults.sessionReport && (
          <div className="session-report">
            <h2>Session Summary</h2>
            <div className="report-content">
              <pre>{careerResults.sessionReport}</pre>
            </div>
          </div>
        )}

        <div className="actions">
          <button 
            className="btn btn-primary" 
            onClick={() => navigate('/assessment')}
          >
            <GraduationCap size={20} />
            Find Matching Colleges
          </button>
          <button 
            className="btn btn-secondary" 
            onClick={() => navigate('/career-assessment')}
          >
            <Brain size={20} />
            Retake Assessment
          </button>
        </div>
      </div>

      <style jsx="true">{`
        .career-results {
          padding: 2rem 0;
          min-height: 100vh;
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }

        .container {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 1rem;
        }

        .header {
          text-align: center;
          margin-bottom: 3rem;
          color: white;
        }

        .header h1 {
          font-size: 2.5rem;
          margin: 1rem 0;
          font-weight: 700;
        }

        .header p {
          font-size: 1.2rem;
          opacity: 0.9;
        }

        .results-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
          gap: 2rem;
          margin-bottom: 3rem;
        }

        .career-card {
          background: white;
          border-radius: 12px;
          padding: 2rem;
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
          transition: transform 0.2s ease;
        }

        .career-card:hover {
          transform: translateY(-5px);
        }

        .career-header {
          display: flex;
          align-items: flex-start;
          margin-bottom: 1.5rem;
        }

        .career-icon {
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
          padding: 1rem;
          border-radius: 12px;
          margin-right: 1rem;
        }

        .career-info h3 {
          margin: 0 0 0.5rem 0;
          font-size: 1.5rem;
          color: #333;
        }

        .category {
          display: inline-block;
          background: #f0f0f0;
          color: #666;
          padding: 0.25rem 0.75rem;
          border-radius: 20px;
          font-size: 0.875rem;
          margin-bottom: 0.5rem;
        }

        .match-score {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }

        .score {
          font-size: 1.5rem;
          font-weight: 700;
          color: #667eea;
        }

        .label {
          color: #666;
          font-size: 0.875rem;
        }

        .description {
          color: #666;
          line-height: 1.6;
          margin-bottom: 1.5rem;
        }

        .career-details {
          margin-bottom: 1.5rem;
        }

        .detail-item {
          margin-bottom: 0.5rem;
          color: #555;
        }

        .detail-item strong {
          color: #333;
        }

        .explanation, .skills-gap {
          background: #f8f9fa;
          padding: 1rem;
          border-radius: 8px;
          margin-bottom: 1rem;
        }

        .explanation h4, .skills-gap h4 {
          margin: 0 0 0.5rem 0;
          color: #333;
          font-size: 1rem;
        }

        .skills-gap ul {
          margin: 0;
          padding-left: 1.5rem;
        }

        .skills-gap li {
          margin-bottom: 0.25rem;
          color: #666;
        }

        .session-report {
          background: white;
          border-radius: 12px;
          padding: 2rem;
          margin-bottom: 2rem;
          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
        }

        .session-report h2 {
          margin: 0 0 1rem 0;
          color: #333;
        }

        .report-content {
          background: #f8f9fa;
          padding: 1rem;
          border-radius: 8px;
          max-height: 400px;
          overflow-y: auto;
        }

        .report-content pre {
          margin: 0;
          white-space: pre-wrap;
          font-family: inherit;
          color: #555;
        }

        .actions {
          display: flex;
          gap: 1rem;
          justify-content: center;
          flex-wrap: wrap;
        }

        .btn {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 0.75rem 1.5rem;
          border: none;
          border-radius: 8px;
          font-size: 1rem;
          font-weight: 600;
          cursor: pointer;
          transition: all 0.2s ease;
          text-decoration: none;
        }

        .btn-primary {
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
          color: white;
        }

        .btn-primary:hover {
          transform: translateY(-2px);
          box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }

        .btn-secondary {
          background: white;
          color: #667eea;
          border: 2px solid #667eea;
        }

        .btn-secondary:hover {
          background: #667eea;
          color: white;
          transform: translateY(-2px);
        }

        @media (max-width: 768px) {
          .results-grid {
            grid-template-columns: 1fr;
          }

          .career-card {
            padding: 1.5rem;
          }

          .header h1 {
            font-size: 2rem;
          }

          .actions {
            flex-direction: column;
            align-items: center;
          }
        }
      `}</style>
    </div>
  );
};

export default CareerResults; 