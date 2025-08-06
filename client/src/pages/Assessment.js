import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, ArrowLeft, Upload, Plus, X } from 'lucide-react';
import { useTheme } from '../App';
import axios from 'axios';

const Assessment = ({ setAssessmentData, setMatches }) => {
  const navigate = useNavigate();
  const { isDarkMode } = useTheme();
  
  // Create local state if props are not provided
  const [localAssessmentData, setLocalAssessmentData] = useState(null);
  const [localMatches, setLocalMatches] = useState([]);
  
  // Use props if provided, otherwise use local state
  const assessmentDataHandler = setAssessmentData || setLocalAssessmentData;
  const matchesHandler = setMatches || setLocalMatches;
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [formData, setFormData] = useState({
    // Personal Information
    firstName: '',
    lastName: '',
    email: '',
    phone: '',
    homeState: '',
    
    // Personality
    personalityType: '',
    learningStyle: '',
    socialPreference: '',
    stressManagement: '',
    climatePreference: '',
    
    // Academic Information
    currentGPA: '',
    gradeTrend: '',
    desiredMajor: '',
    preferredSize: '',
    preferredLocation: '',
    
    // Financial Information
    maxBudget: '',
    financialAid: '',
    workStudy: false,
    
    // Extracurricular Activities
    activities: [],
    
    // Course History
    courses: [],
    
    // Resume
    resume: null
  });

  const steps = [
    { title: 'Personal Information', key: 'personal' },
    { title: 'Personality Assessment', key: 'personality' },
    { title: 'Academic Profile', key: 'academic' },
    { title: 'Financial Information', key: 'financial' },
    { title: 'Extracurricular Activities', key: 'activities' },
    { title: 'Course History', key: 'courses' },
    { title: 'Resume Upload', key: 'resume' },
    { title: 'Review & Submit', key: 'review' }
  ];

  const personalityQuestions = [
    {
      question: "How would you describe your personality type?",
      options: [
        { value: "analytical", label: "Analytical - I enjoy solving complex problems and working with data" },
        { value: "creative", label: "Creative - I thrive in artistic and innovative environments" },
        { value: "social", label: "Social - I love working with people and building relationships" },
        { value: "ambitious", label: "Ambitious - I'm driven to achieve and lead" },
        { value: "balanced", label: "Balanced - I adapt well to different situations" },
        { value: "progressive", label: "Progressive - I value social justice and innovation" }
      ]
    },
    {
      question: "What's your preferred learning style?",
      options: [
        { value: "visual", label: "Visual - I learn best through diagrams, charts, and visual aids" },
        { value: "auditory", label: "Auditory - I learn best through listening and discussion" },
        { value: "kinesthetic", label: "Hands-on - I learn best through doing and practical experience" },
        { value: "reading", label: "Reading/Writing - I learn best through text and written materials" }
      ]
    },
    {
      question: "How do you prefer to spend your free time?",
      options: [
        { value: "social", label: "Hanging out with friends and attending social events" },
        { value: "solitary", label: "Quiet time alone for reflection and personal projects" },
        { value: "active", label: "Physical activities and outdoor adventures" },
        { value: "intellectual", label: "Reading, research, and intellectual pursuits" }
      ]
    },
    {
      question: "How do you typically handle stress?",
      options: [
        { value: "structured", label: "I prefer structured environments with clear expectations" },
        { value: "flexible", label: "I adapt well to changing situations and flexible schedules" },
        { value: "supportive", label: "I rely on support from friends, family, and mentors" },
        { value: "independent", label: "I handle challenges independently and self-motivate" }
      ]
    },
    {
      question: "What climate do you prefer?",
      options: [
        { value: "warm", label: "Warm - I enjoy sunny, warm weather year-round" },
        { value: "moderate", label: "Moderate - I prefer mild temperatures with seasons" },
        { value: "cold", label: "Cold - I enjoy four distinct seasons including winter" }
      ]
    }
  ];

  const majors = [
    "Computer Science", "Engineering", "Business", "Psychology", "Biology", 
    "Chemistry", "Physics", "Mathematics", "English", "History", "Political Science",
    "Economics", "Sociology", "Anthropology", "Art", "Music", "Theater", "Film",
    "Journalism", "Communications", "Education", "Nursing", "Medicine", "Law",
    "Architecture", "Design", "Environmental Science", "Agriculture", "Veterinary",
    "Pharmacy", "Dentistry", "Public Health", "Social Work", "Criminal Justice"
  ];

  const handleInputChange = (field, value) => {
    setFormData(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const handleActivityAdd = () => {
    setFormData(prev => ({
      ...prev,
      activities: [...prev.activities, { name: '', role: '', hours: '' }]
    }));
  };

  const handleActivityChange = (index, field, value) => {
    setFormData(prev => ({
      ...prev,
      activities: prev.activities.map((activity, i) => 
        i === index ? { ...activity, [field]: value } : activity
      )
    }));
  };

  const handleActivityRemove = (index) => {
    setFormData(prev => ({
      ...prev,
      activities: prev.activities.filter((_, i) => i !== index)
    }));
  };

  const handleCourseAdd = () => {
    setFormData(prev => ({
      ...prev,
      courses: [...prev.courses, { name: '', grade: '', credits: '' }]
    }));
  };

  const handleCourseChange = (index, field, value) => {
    setFormData(prev => ({
      ...prev,
      courses: prev.courses.map((course, i) => 
        i === index ? { ...course, [field]: value } : course
      )
    }));
  };

  const handleCourseRemove = (index) => {
    setFormData(prev => ({
      ...prev,
      courses: prev.courses.filter((_, i) => i !== index)
    }));
  };

  const handleResumeUpload = (event) => {
    const file = event.target.files[0];
    if (file) {
      setFormData(prev => ({
        ...prev,
        resume: file
      }));
    }
  };

  const handleSubmit = async () => {
    try {
      // Upload resume if provided
      let resumeData = null;
      if (formData.resume) {
        const formDataResume = new FormData();
        formDataResume.append('resume', formData.resume);
        const uploadResponse = await axios.post('/api/upload/resume', formDataResume);
        resumeData = uploadResponse.data;
      }

      // Submit assessment
      const assessmentPayload = {
        ...formData,
        resume: resumeData
      };

      const response = await axios.post('/api/assessment', assessmentPayload);
      
      assessmentDataHandler(assessmentPayload);
      matchesHandler(response.data.matches);
      navigate('/results');
    } catch (error) {
      console.error('Error submitting assessment:', error);
      alert('There was an error submitting your assessment. Please try again.');
    }
  };

  const renderStep = () => {
    switch (currentStep) {
      case 0: // Personal Information
        return (
          <div className="step-content">
            <h2>Personal Information</h2>
            <p>Let's start with some basic information about you.</p>
            
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">First Name</label>
                <input
                  type="text"
                  className="form-input"
                  value={formData.firstName}
                  onChange={(e) => handleInputChange('firstName', e.target.value)}
                  required
                />
              </div>
              
              <div className="form-group">
                <label className="form-label">Last Name</label>
                <input
                  type="text"
                  className="form-input"
                  value={formData.lastName}
                  onChange={(e) => handleInputChange('lastName', e.target.value)}
                  required
                />
              </div>
              
              <div className="form-group">
                <label className="form-label">Email</label>
                <input
                  type="email"
                  className="form-input"
                  value={formData.email}
                  onChange={(e) => handleInputChange('email', e.target.value)}
                  required
                />
              </div>
              
              <div className="form-group">
                <label className="form-label">Phone Number</label>
                <input
                  type="tel"
                  className="form-input"
                  value={formData.phone}
                  onChange={(e) => handleInputChange('phone', e.target.value)}
                />
              </div>
              
              <div className="form-group">
                <label className="form-label">Home State</label>
                <select
                  className="form-select"
                  value={formData.homeState}
                  onChange={(e) => handleInputChange('homeState', e.target.value)}
                >
                  <option value="">Select your home state</option>
                  <option value="California">California</option>
                  <option value="Texas">Texas</option>
                  <option value="Florida">Florida</option>
                  <option value="New York">New York</option>
                  <option value="Massachusetts">Massachusetts</option>
                  <option value="Michigan">Michigan</option>
                  <option value="Washington">Washington</option>
                  <option value="North Carolina">North Carolina</option>
                  <option value="Other">Other</option>
                </select>
              </div>
            </div>
          </div>
        );

      case 1: // Personality Assessment
        return (
          <div className="step-content">
            <h2>Personality Assessment</h2>
            <p>Help us understand your personality and preferences to find the best college match.</p>
            
            {personalityQuestions.map((question, index) => (
              <div key={index} className="form-group">
                <label className="form-label">{question.question}</label>
                <div className="radio-group">
                  {question.options.map((option) => (
                    <label key={option.value} className="radio-option">
                      <input
                        type="radio"
                        name={`personality-${index}`}
                        value={option.value}
                        checked={formData[Object.keys(formData)[index + 4]] === option.value}
                        onChange={(e) => handleInputChange(Object.keys(formData)[index + 4], e.target.value)}
                      />
                      <span className="radio-label">{option.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        );

      case 2: // Academic Profile
        return (
          <div className="step-content">
            <h2>Academic Profile</h2>
            <p>Tell us about your academic background and preferences.</p>
            
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Current GPA</label>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  max="4.0"
                  className="form-input"
                  value={formData.currentGPA}
                  onChange={(e) => handleInputChange('currentGPA', e.target.value)}
                  placeholder="e.g., 3.75"
                />
              </div>
              
              <div className="form-group">
                <label className="form-label">Grade Trend</label>
                <select
                  className="form-select"
                  value={formData.gradeTrend}
                  onChange={(e) => handleInputChange('gradeTrend', e.target.value)}
                >
                  <option value="">Select your grade trend</option>
                  <option value="upward">Upward - My grades have improved over time</option>
                  <option value="consistent">Consistent - My grades have stayed high</option>
                  <option value="downward">Downward - My grades have declined</option>
                  <option value="mixed">Mixed - My grades have varied</option>
                </select>
              </div>
              
              <div className="form-group">
                <label className="form-label">Desired Major</label>
                <select
                  className="form-select"
                  value={formData.desiredMajor}
                  onChange={(e) => handleInputChange('desiredMajor', e.target.value)}
                >
                  <option value="">Select a major</option>
                  {majors.map(major => (
                    <option key={major} value={major}>{major}</option>
                  ))}
                </select>
              </div>
              
              <div className="form-group">
                <label className="form-label">Preferred School Size</label>
                <select
                  className="form-select"
                  value={formData.preferredSize}
                  onChange={(e) => handleInputChange('preferredSize', e.target.value)}
                >
                  <option value="">Select size preference</option>
                  <option value="5000">Small (under 5,000 students)</option>
                  <option value="15000">Medium (5,000-15,000 students)</option>
                  <option value="30000">Large (15,000-30,000 students)</option>
                  <option value="50000">Very Large (over 30,000 students)</option>
                </select>
              </div>
              
              <div className="form-group">
                <label className="form-label">Preferred Location</label>
                <input
                  type="text"
                  className="form-input"
                  value={formData.preferredLocation}
                  onChange={(e) => handleInputChange('preferredLocation', e.target.value)}
                  placeholder="e.g., California, New York, Texas"
                />
              </div>
            </div>
          </div>
        );

      case 3: // Financial Information
        return (
          <div className="step-content">
            <h2>Financial Information</h2>
            <p>Help us understand your financial situation and preferences.</p>
            
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Maximum Annual Budget (including tuition, housing, etc.)</label>
                <input
                  type="number"
                  className="form-input"
                  value={formData.maxBudget}
                  onChange={(e) => handleInputChange('maxBudget', e.target.value)}
                  placeholder="e.g., 50000"
                />
              </div>
              
              <div className="form-group">
                <label className="form-label">Do you plan to apply for financial aid?</label>
                <select
                  className="form-select"
                  value={formData.financialAid}
                  onChange={(e) => handleInputChange('financialAid', e.target.value)}
                >
                  <option value="">Select option</option>
                  <option value="yes">Yes, I will apply for financial aid</option>
                  <option value="no">No, I will not apply for financial aid</option>
                  <option value="maybe">Maybe, I'm not sure yet</option>
                </select>
              </div>
              
              <div className="form-group">
                <label className="radio-option">
                  <input
                    type="checkbox"
                    checked={formData.workStudy}
                    onChange={(e) => handleInputChange('workStudy', e.target.checked)}
                  />
                  <span className="radio-label">I'm interested in work-study programs</span>
                </label>
              </div>
            </div>
          </div>
        );

      case 4: // Extracurricular Activities
        return (
          <div className="step-content">
            <h2>Extracurricular Activities</h2>
            <p>Tell us about your extracurricular activities and leadership roles.</p>
            
            {formData.activities.map((activity, index) => (
              <div key={index} className="activity-item">
                <div className="form-grid">
                  <div className="form-group">
                    <label className="form-label">Activity Name</label>
                    <input
                      type="text"
                      className="form-input"
                      value={activity.name}
                      onChange={(e) => handleActivityChange(index, 'name', e.target.value)}
                      placeholder="e.g., Student Council, Soccer Team"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label className="form-label">Your Role</label>
                    <input
                      type="text"
                      className="form-input"
                      value={activity.role}
                      onChange={(e) => handleActivityChange(index, 'role', e.target.value)}
                      placeholder="e.g., President, Captain, Member"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label className="form-label">Hours per Week</label>
                    <input
                      type="number"
                      className="form-input"
                      value={activity.hours}
                      onChange={(e) => handleActivityChange(index, 'hours', e.target.value)}
                      placeholder="e.g., 5"
                    />
                  </div>
                  
                  <div className="form-group">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => handleActivityRemove(index)}
                    >
                      <X size={16} />
                      Remove
                    </button>
                  </div>
                </div>
              </div>
            ))}
            
            <button
              type="button"
              className="btn btn-outline"
              onClick={handleActivityAdd}
            >
              <Plus size={16} />
              Add Activity
            </button>
          </div>
        );

      case 5: // Course History
        return (
          <div className="step-content">
            <h2>Course History</h2>
            <p>Add your most relevant courses and grades.</p>
            
            {formData.courses.map((course, index) => (
              <div key={index} className="course-item">
                <div className="form-grid">
                  <div className="form-group">
                    <label className="form-label">Course Name</label>
                    <input
                      type="text"
                      className="form-input"
                      value={course.name}
                      onChange={(e) => handleCourseChange(index, 'name', e.target.value)}
                      placeholder="e.g., AP Calculus BC, Honors English"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label className="form-label">Grade</label>
                    <input
                      type="text"
                      className="form-input"
                      value={course.grade}
                      onChange={(e) => handleCourseChange(index, 'grade', e.target.value)}
                      placeholder="e.g., A, 95, 4.0"
                    />
                  </div>
                  
                  <div className="form-group">
                    <label className="form-label">Credits</label>
                    <input
                      type="number"
                      className="form-input"
                      value={course.credits}
                      onChange={(e) => handleCourseChange(index, 'credits', e.target.value)}
                      placeholder="e.g., 1"
                    />
                  </div>
                  
                  <div className="form-group">
                    <button
                      type="button"
                      className="btn btn-secondary"
                      onClick={() => handleCourseRemove(index)}
                    >
                      <X size={16} />
                      Remove
                    </button>
                  </div>
                </div>
              </div>
            ))}
            
            <button
              type="button"
              className="btn btn-outline"
              onClick={handleCourseAdd}
            >
              <Plus size={16} />
              Add Course
            </button>
          </div>
        );

      case 6: // Resume Upload
        return (
          <div className="step-content">
            <h2>Resume Upload</h2>
            <p>Upload your resume or CV to help us better understand your background (optional).</p>
            
            <div className="form-group">
              <label className="form-label">Resume/CV</label>
              <div className="file-upload">
                <input
                  type="file"
                  accept=".pdf,.doc,.docx"
                  onChange={handleResumeUpload}
                  id="resume-upload"
                  className="file-input"
                />
                <label htmlFor="resume-upload" className="file-label">
                  <Upload size={20} />
                  {formData.resume ? formData.resume.name : 'Choose a file or drag it here'}
                </label>
              </div>
              {formData.resume && (
                <p className="file-info">Selected: {formData.resume.name}</p>
              )}
            </div>
          </div>
        );

      case 7: // Review & Submit
        return (
          <div className="step-content">
            <h2>Review Your Information</h2>
            <p>Please review your information before submitting.</p>
            
            <div className="review-section">
              <h3>Personal Information</h3>
              <p><strong>Name:</strong> {formData.firstName} {formData.lastName}</p>
              <p><strong>Email:</strong> {formData.email}</p>
              <p><strong>Phone:</strong> {formData.phone}</p>
            </div>
            
            <div className="review-section">
              <h3>Academic Profile</h3>
              <p><strong>GPA:</strong> {formData.currentGPA}</p>
              <p><strong>Desired Major:</strong> {formData.desiredMajor}</p>
              <p><strong>Preferred Size:</strong> {formData.preferredSize}</p>
              <p><strong>Preferred Location:</strong> {formData.preferredLocation}</p>
            </div>
            
            <div className="review-section">
              <h3>Financial Information</h3>
              <p><strong>Max Budget:</strong> ${formData.maxBudget}</p>
              <p><strong>Financial Aid:</strong> {formData.financialAid}</p>
              <p><strong>Work Study:</strong> {formData.workStudy ? 'Yes' : 'No'}</p>
            </div>
            
            {formData.activities.length > 0 && (
              <div className="review-section">
                <h3>Extracurricular Activities</h3>
                {formData.activities.map((activity, index) => (
                  <p key={index}>
                    <strong>{activity.name}</strong> - {activity.role} ({activity.hours} hrs/week)
                  </p>
                ))}
              </div>
            )}
            
            {formData.courses.length > 0 && (
              <div className="review-section">
                <h3>Course History</h3>
                {formData.courses.map((course, index) => (
                  <p key={index}>
                    <strong>{course.name}</strong> - Grade: {course.grade} ({course.credits} credits)
                  </p>
                ))}
              </div>
            )}
            
            {formData.resume && (
              <div className="review-section">
                <h3>Resume</h3>
                <p><strong>File:</strong> {formData.resume.name}</p>
              </div>
            )}
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div className="assessment">
      <div className="assessment-container">
        {/* Progress Bar */}
        <div className="progress-section">
          <div className="progress-bar">
            <div 
              className="progress-fill" 
              style={{ width: `${((currentStep + 1) / steps.length) * 100}%` }}
            ></div>
          </div>
          <p className="progress-text">
            Step {currentStep + 1} of {steps.length}: {steps[currentStep].title}
          </p>
        </div>

        {/* Step Content */}
        <div className="step-container">
          {renderStep()}
        </div>

        {/* Navigation */}
        <div className="step-navigation">
          {currentStep > 0 && (
            <button
              className="btn btn-secondary"
              onClick={() => setCurrentStep(currentStep - 1)}
            >
              <ArrowLeft size={16} />
              Previous
            </button>
          )}
          
          {currentStep < steps.length - 1 ? (
            <button
              className="btn btn-primary"
              onClick={() => setCurrentStep(currentStep + 1)}
            >
              Next
              <ArrowRight size={16} />
            </button>
          ) : (
            <button
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={loading}
            >
              {loading ? 'Submitting...' : 'Submit Assessment'}
              <ArrowRight size={16} />
            </button>
          )}
        </div>
      </div>

      <style jsx="true">{`
        .assessment {
          min-height: 100vh;
          padding: 2rem 0;
          background: var(--bg-primary);
        }
        
        .assessment-container {
          max-width: 800px;
          margin: 0 auto;
          padding: 0 2rem;
        }
        
        .progress-section {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          margin-bottom: 2rem;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .progress-bar {
          width: 100%;
          height: 12px;
          background: var(--bg-secondary);
          border-radius: 8px;
          overflow: hidden;
          margin-bottom: 1rem;
        }
        
        .progress-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--primary-color), var(--accent-color));
          transition: width 0.3s ease;
          border-radius: 8px;
        }
        
        .progress-text {
          text-align: center;
          margin-top: 0.5rem;
          color: var(--text-secondary);
          font-weight: 600;
          font-size: 1.1rem;
        }
        
        .step-container {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          margin-bottom: 2rem;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .step-content h2 {
          font-size: 2rem;
          font-weight: 700;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
        }
        
        .step-content p {
          margin-bottom: 2rem;
          color: var(--text-secondary);
          font-size: 1.1rem;
          line-height: 1.6;
        }
        
        .form-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
          gap: 1.5rem;
        }
        
        .form-group {
          margin-bottom: 1.5rem;
        }
        
        .form-label {
          display: block;
          font-weight: 600;
          margin-bottom: 0.5rem;
          color: var(--text-primary);
          font-size: 1rem;
        }
        
        .form-input,
        .form-select {
          width: 100%;
          padding: 0.75rem 1rem;
          border: 2px solid var(--border-color);
          border-radius: 8px;
          font-size: 1rem;
          background: var(--bg-primary);
          color: var(--text-primary);
          transition: all 0.2s ease;
        }
        
        .form-input:focus,
        .form-select:focus {
          outline: none;
          border-color: var(--primary-color);
          box-shadow: 0 0 0 3px var(--primary-color-alpha);
        }
        
        .radio-group {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }
        
        .radio-option {
          display: flex;
          align-items: flex-start;
          gap: 0.75rem;
          cursor: pointer;
          padding: 1rem;
          border: 2px solid var(--border-color);
          border-radius: 12px;
          transition: all 0.2s ease;
          background: var(--bg-primary);
        }
        
        .radio-option:hover {
          border-color: var(--primary-color);
          background: var(--bg-secondary);
          transform: translateY(-2px);
          box-shadow: 0 4px 12px var(--shadow-color);
        }
        
        .radio-option input[type="radio"] {
          margin-top: 0.25rem;
        }
        
        .radio-option input[type="checkbox"] {
          margin-top: 0.25rem;
        }
        
        .radio-label {
          flex: 1;
          color: var(--text-primary);
          font-weight: 500;
          line-height: 1.5;
        }
        
        .activity-item,
        .course-item {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 1.5rem;
          margin-bottom: 1.5rem;
          transition: all 0.2s ease;
        }
        
        .activity-item:hover,
        .course-item:hover {
          box-shadow: 0 4px 12px var(--shadow-color);
          transform: translateY(-2px);
        }
        
        .file-upload {
          position: relative;
        }
        
        .file-input {
          position: absolute;
          opacity: 0;
          width: 100%;
          height: 100%;
          cursor: pointer;
        }
        
        .file-label {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          padding: 1.5rem;
          border: 2px dashed var(--border-color);
          border-radius: 12px;
          cursor: pointer;
          transition: all 0.2s ease;
          color: var(--text-secondary);
          background: var(--bg-secondary);
        }
        
        .file-label:hover {
          border-color: var(--primary-color);
          color: var(--primary-color);
          background: var(--bg-primary);
        }
        
        .file-info {
          margin-top: 0.5rem;
          font-size: 0.875rem;
          color: var(--text-secondary);
        }
        
        .review-section {
          background: var(--bg-secondary);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 1.5rem;
          margin-bottom: 1.5rem;
          transition: all 0.2s ease;
        }
        
        .review-section:hover {
          box-shadow: 0 4px 12px var(--shadow-color);
        }
        
        .review-section h3 {
          margin-bottom: 0.5rem;
          color: var(--text-primary);
          font-weight: 600;
        }
        
        .review-section p {
          margin-bottom: 0.25rem;
          color: var(--text-secondary);
        }
        
        .step-navigation {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 2rem;
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        @media (max-width: 768px) {
          .assessment {
            padding: 1rem 0;
          }
          
          .assessment-container {
            padding: 0 1rem;
          }
          
          .progress-section,
          .step-container,
          .step-navigation {
            padding: 1.5rem;
          }
          
          .form-grid {
            grid-template-columns: 1fr;
            gap: 1rem;
          }
          
          .step-navigation {
            flex-direction: column;
            gap: 1rem;
          }
          
          .step-content h2 {
            font-size: 1.5rem;
          }
          
          .step-content p {
            font-size: 1rem;
          }
        }
      `}</style>
    </div>
  );
};

export default Assessment; 