require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const multer = require('multer');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 5001;

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// File upload configuration
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const uploadDir = path.join(__dirname, 'uploads');
    if (!fs.existsSync(uploadDir)) {
      fs.mkdirSync(uploadDir, { recursive: true });
    }
    cb(null, uploadDir);
  },
  filename: (req, file, cb) => {
    cb(null, Date.now() + '-' + file.originalname);
  }
});

const upload = multer({ storage });

// Sample data
const schools = require('./data/schools.json');
const reviews = require('./data/reviews.json');
const assessments = [];

// Routes

// Assessment submission
app.post('/api/assessment', (req, res) => {
  try {
    const assessment = {
      id: Date.now().toString(),
      ...req.body,
      timestamp: new Date().toISOString()
    };
    assessments.push(assessment);
    
    // Simple matching algorithm
    const matches = calculateMatches(assessment, schools);
    
    res.json({
      success: true,
      assessmentId: assessment.id,
      matches: matches.slice(0, 10) // Top 10 matches
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get schools with filters
app.get('/api/schools', (req, res) => {
  try {
    let filteredSchools = [...schools];
    const { location, maxCost, minGPA, maxAcceptanceRate, minPopulation, maxPopulation } = req.query;

    if (location) {
      filteredSchools = filteredSchools.filter(school => 
        school.location.toLowerCase().includes(location.toLowerCase())
      );
    }

    if (maxCost) {
      filteredSchools = filteredSchools.filter(school => 
        school.tuition <= parseInt(maxCost)
      );
    }

    if (minGPA) {
      filteredSchools = filteredSchools.filter(school => 
        school.averageGPA >= parseFloat(minGPA)
      );
    }

    if (maxAcceptanceRate) {
      filteredSchools = filteredSchools.filter(school => 
        school.acceptanceRate <= parseInt(maxAcceptanceRate)
      );
    }

    if (minPopulation) {
      filteredSchools = filteredSchools.filter(school => 
        school.studentPopulation >= parseInt(minPopulation)
      );
    }

    if (maxPopulation) {
      filteredSchools = filteredSchools.filter(school => 
        school.studentPopulation <= parseInt(maxPopulation)
      );
    }

    res.json({ success: true, schools: filteredSchools });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get detailed school profile
app.get('/api/schools/:id', (req, res) => {
  try {
    const school = schools.find(s => s.id === req.params.id);
    if (!school) {
      return res.status(404).json({ success: false, error: 'School not found' });
    }

    const schoolReviews = reviews.filter(r => r.schoolId === req.params.id);
    
    res.json({
      success: true,
      school: { ...school, reviews: schoolReviews }
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Upload resume
app.post('/api/upload/resume', upload.single('resume'), (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ success: false, error: 'No file uploaded' });
    }

    res.json({
      success: true,
      filename: req.file.filename,
      originalName: req.file.originalname,
      size: req.file.size
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Submit review
app.post('/api/reviews', (req, res) => {
  try {
    const review = {
      id: Date.now().toString(),
      ...req.body,
      timestamp: new Date().toISOString()
    };
    
    reviews.push(review);
    
    res.json({ success: true, review });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Get school reviews
app.get('/api/reviews/:schoolId', (req, res) => {
  try {
    const schoolReviews = reviews.filter(r => r.schoolId === req.params.schoolId);
    res.json({ success: true, reviews: schoolReviews });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// Import advanced matching algorithm
const CollegeMatchingAlgorithm = require('./algorithms/matchingAlgorithm');
const CareerMatchingAlgorithm = require('./algorithms/careerMatchingAlgorithm');
const AICounselor = require('./services/aiCounselor');

// Initialize the matching algorithms
const matchingAlgorithm = new CollegeMatchingAlgorithm();
const careerMatchingAlgorithm = new CareerMatchingAlgorithm();
const aiCounselor = new AICounselor();

// Advanced matching algorithm
function calculateMatches(assessment, schools) {
  return matchingAlgorithm.calculateMatches(assessment, schools);
}

// Career Assessment Routes

// Get career assessment data
app.get('/api/career-assessment/data', (req, res) => {
  try {
    const careerAssessment = require('./data/careerAssessment');
    res.json(careerAssessment);
  } catch (error) {
    console.error('Error loading career assessment data:', error);
    res.status(500).json({ error: 'Failed to load assessment data' });
  }
});

// Submit form-based career assessment
app.post('/api/career-assessment/form', async (req, res) => {
  try {
    const assessmentData = req.body;
    
    // Generate career recommendations
    const careerMatches = careerMatchingAlgorithm.generateCareerRecommendations(assessmentData);
    
    res.json({ careerMatches });
  } catch (error) {
    console.error('Error processing career assessment:', error);
    res.status(500).json({ error: 'Failed to process career assessment' });
  }
});

// Initialize AI voice counselor session
app.post('/api/career-assessment/voice/initialize', async (req, res) => {
  try {
    const { studentName } = req.body;
    const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    
    // Initialize session
    const session = aiCounselor.initializeSession(sessionId, studentName);
    
    // Generate welcome message
    const welcomeMessage = `Hi ${studentName}! I'm Alex, your AI career counselor. I'm here to help you discover your ideal career path through a natural conversation. We'll explore your interests, skills, values, and goals together. Are you ready to begin?`;
    
    res.json({
      sessionId: sessionId,
      welcomeMessage: welcomeMessage,
      session: session
    });
  } catch (error) {
    console.error('Error initializing voice session:', error);
    res.status(500).json({ error: 'Failed to initialize session' });
  }
});

// Chat with AI counselor
app.post('/api/career-assessment/voice/chat', async (req, res) => {
  try {
    const { sessionId, message } = req.body;
    
    // Generate AI response
    const response = await aiCounselor.generateResponse(sessionId, message);
    
    res.json(response);
  } catch (error) {
    console.error('Error generating AI response:', error);
    res.status(500).json({ error: 'Failed to generate response' });
  }
});

// Complete voice session and get recommendations
app.post('/api/career-assessment/voice/complete', async (req, res) => {
  try {
    const { sessionId } = req.body;
    
    // Generate career recommendations
    const careerRecommendations = await aiCounselor.generateCareerRecommendations(sessionId);
    
    // Generate session report
    const sessionReport = await aiCounselor.generateSessionReport(sessionId);
    
    // Clean up session
    aiCounselor.cleanupSession(sessionId);
    
    res.json({
      careerMatches: careerRecommendations,
      sessionReport: sessionReport
    });
  } catch (error) {
    console.error('Error completing voice session:', error);
    res.status(500).json({ error: 'Failed to complete session' });
  }
});

// Get session status
app.get('/api/career-assessment/voice/status/:sessionId', (req, res) => {
  try {
    const { sessionId } = req.params;
    const status = aiCounselor.getSessionStatus(sessionId);
    
    if (!status) {
      return res.status(404).json({ error: 'Session not found' });
    }
    
    res.json(status);
  } catch (error) {
    console.error('Error getting session status:', error);
    res.status(500).json({ error: 'Failed to get session status' });
  }
});

// Pause session
app.post('/api/career-assessment/voice/pause/:sessionId', (req, res) => {
  try {
    const { sessionId } = req.params;
    aiCounselor.pauseSession(sessionId);
    res.json({ message: 'Session paused' });
  } catch (error) {
    console.error('Error pausing session:', error);
    res.status(500).json({ error: 'Failed to pause session' });
  }
});

// Resume session
app.post('/api/career-assessment/voice/resume/:sessionId', (req, res) => {
  try {
    const { sessionId } = req.params;
    aiCounselor.resumeSession(sessionId);
    res.json({ message: 'Session resumed' });
  } catch (error) {
    console.error('Error resuming session:', error);
    res.status(500).json({ error: 'Failed to resume session' });
  }
});

// Serve static files in production
if (process.env.NODE_ENV === 'production') {
  app.use(express.static(path.join(__dirname, '../client/build')));
  
  app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, '../client/build', 'index.html'));
  });
}

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
}); 