import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Mic, MicOff, MessageCircle, 
  CheckCircle, ArrowRight, ArrowLeft, Clock, User, 
  Brain, Heart, Briefcase, GraduationCap, Pause
} from 'lucide-react';
import { useTheme } from '../App';
import axios from 'axios';

const CareerAssessment = () => {
  const navigate = useNavigate();
  const { isDarkMode } = useTheme();
  const [assessmentType, setAssessmentType] = useState(null); // 'form' or 'voice'
  const [currentStep, setCurrentStep] = useState(0);
  const [formData, setFormData] = useState({});
  const [loading, setLoading] = useState(false);
  const [assessmentData, setAssessmentData] = useState(null);
  
  // Voice counselor state
  const [isRecording, setIsRecording] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [transcription, setTranscription] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [conversationHistory, setConversationHistory] = useState([]);
  const [sessionPhase, setSessionPhase] = useState('introduction');
  const [mediaRecorder, setMediaRecorder] = useState(null);
  const [isAISpeaking, setIsAISpeaking] = useState(false);
  const [isPaused, setIsPaused] = useState(false); // New state for pause
  const [chatMinimized, setChatMinimized] = useState(false); // New state for chat minimization
  const chatEndRef = useRef(null); // Ref for chat messages to scroll to bottom

  // Audio visualization components
  const AudioVisualizer = ({ isActive, type = 'listening' }) => {
    const canvasRef = useRef(null);
    const animationRef = useRef(null);
    
    useEffect(() => {
      if (!isActive || !canvasRef.current) return;
      
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      const bars = 20;
      const barWidth = canvas.width / bars;
      
      const animate = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        for (let i = 0; i < bars; i++) {
          const height = Math.random() * (canvas.height * 0.8) + (canvas.height * 0.1);
          const x = i * barWidth;
          const y = canvas.height - height;
          
          // Different colors for AI speaking vs listening
          if (type === 'speaking') {
            ctx.fillStyle = `hsl(${200 + Math.random() * 60}, 70%, 60%)`;
          } else {
            ctx.fillStyle = `hsl(${120 + Math.random() * 60}, 70%, 60%)`;
          }
          
          ctx.fillRect(x, y, barWidth - 2, height);
        }
        
        animationRef.current = requestAnimationFrame(animate);
      };
      
      animate();
      
      return () => {
        if (animationRef.current) {
          cancelAnimationFrame(animationRef.current);
        }
      };
    }, [isActive, type]);
    
    return (
      <canvas
        ref={canvasRef}
        width={200}
        height={60}
        style={{
          border: '1px solid #e2e8f0',
          borderRadius: '8px',
          background: '#f8fafc'
        }}
      />
    );
  };

  // Assessment sections
  const sections = [
    {
      id: 'academic',
      title: 'Academic & Educational Background',
      icon: <GraduationCap size={24} />,
      description: 'Understanding your educational foundation and learning preferences'
    },
    {
      id: 'work_style',
      title: 'Work Style & Environment Preferences',
      icon: <Briefcase size={24} />,
      description: 'Understanding how you prefer to work and what environments suit you best'
    },
    {
      id: 'interests',
      title: 'Interests & Activities',
      icon: <Heart size={24} />,
      description: 'Discovering your passions, hobbies, and what motivates you'
    },
    {
      id: 'values',
      title: 'Values & Life Priorities',
      icon: <Brain size={24} />,
      description: 'Identifying your core values and what matters most to you'
    },
    {
      id: 'skills',
      title: 'Skills & Strengths Assessment',
      icon: <CheckCircle size={24} />,
      description: 'Assessing your current abilities and potential areas for growth'
    },
    {
      id: 'future',
      title: 'Future Goals & Concerns',
      icon: <ArrowRight size={24} />,
      description: 'Understanding your career aspirations and potential obstacles'
    }
  ];

  // Handle form input changes
  const handleInputChange = (questionId, value) => {
    setFormData(prev => ({
      ...prev,
      [questionId]: value
    }));
  };

  // Handle multi-select changes
  const handleMultiSelectChange = (questionId, value, checked) => {
    setFormData(prev => {
      const currentValues = prev[questionId] || [];
      if (checked) {
        return {
          ...prev,
          [questionId]: [...currentValues, value]
        };
      } else {
        return {
          ...prev,
          [questionId]: currentValues.filter(v => v !== value)
        };
      }
    });
  };

  // Handle pause/resume functionality
  const handlePauseResume = () => {
    if (isPaused) {
      // Resume session
      setIsPaused(false);
      console.log('Session resumed');
      
      // If AI was speaking, continue speaking
      if (isAISpeaking) {
        console.log('AI was speaking, continuing...');
      } else if (!isListening) {
        // If not listening, start listening after a short delay
        setTimeout(() => {
          if (!isPaused && !isListening && !isAISpeaking) {
            console.log('Resuming session - starting listening');
            startRecordingWithSession(sessionId);
          }
        }, 1000);
      }
    } else {
      // Pause session
      setIsPaused(true);
      console.log('Session paused');
      
      // Stop speech synthesis if AI is speaking
      if (isAISpeaking) {
        window.speechSynthesis.cancel();
        setIsAISpeaking(false);
        console.log('AI speech stopped due to pause');
      }
      
      // Stop speech recognition if listening
      if (isListening && window.recognition) {
        try {
          window.recognition.stop();
          window.recognition = null;
          setIsListening(false);
          setIsRecording(false);
          console.log('Speech recognition stopped due to pause');
        } catch (error) {
          console.log('Error stopping recognition:', error);
        }
      }
    }
  };

  // Load assessment data
  useEffect(() => {
    const loadAssessmentData = async () => {
      try {
        const response = await axios.get('/api/career-assessment/data');
        setAssessmentData(response.data);
      } catch (error) {
        console.error('Error loading assessment data:', error);
        // Use mock data if API fails
        setAssessmentData({
          sections: [
            {
              id: 'academic',
              title: 'Academic & Educational Background',
              questions: [
                {
                  id: 'gpa',
                  question: 'What is your current GPA or grade average?',
                  type: 'select',
                  options: [
                    { value: '4.0', label: '4.0 (A average)' },
                    { value: '3.8', label: '3.8-3.9 (A-/B+ average)' },
                    { value: '3.5', label: '3.5-3.7 (B+ average)' },
                    { value: '3.2', label: '3.2-3.4 (B average)' },
                    { value: '3.0', label: '3.0-3.1 (B- average)' },
                    { value: '2.8', label: '2.8-2.9 (C+ average)' },
                    { value: '2.5', label: '2.5-2.7 (C average)' },
                    { value: '2.0', label: 'Below 2.5' }
                  ]
                },
                {
                  id: 'strongest_subjects',
                  question: 'What are your strongest academic subjects? (Select all that apply)',
                  type: 'multiselect',
                  options: [
                    { value: 'math', label: 'Mathematics' },
                    { value: 'science', label: 'Science (Biology, Chemistry, Physics)' },
                    { value: 'english', label: 'English/Language Arts' },
                    { value: 'history', label: 'History/Social Studies' },
                    { value: 'arts', label: 'Arts (Visual, Music, Theater)' },
                    { value: 'foreign_language', label: 'Foreign Languages' },
                    { value: 'computer_science', label: 'Computer Science' },
                    { value: 'business', label: 'Business/Economics' },
                    { value: 'psychology', label: 'Psychology' },
                    { value: 'physical_education', label: 'Physical Education' }
                  ]
                }
              ]
            }
          ]
        });
      }
    };
    
    if (assessmentType === 'form') {
      loadAssessmentData();
    }
  }, [assessmentType]);

  // Auto-start voice session when voice counselor is selected
  useEffect(() => {
    if (assessmentType === 'voice' && currentStep === 1) {
      console.log('Auto-starting voice session...');
      setTimeout(() => {
        console.log('Calling initializeVoiceSession...');
        initializeVoiceSession();
      }, 1000); // Wait 1 second for component to mount
    }
  }, [assessmentType, currentStep]);

  // Submit form assessment
  const handleFormSubmit = async () => {
    setLoading(true);
    try {
      const response = await axios.post('/api/career-assessment/form', formData);
      navigate('/career-results', { 
        state: { 
          careerResults: response.data,
          assessmentData: formData
        } 
      });
    } catch (error) {
      console.error('Error submitting assessment:', error);
      setLoading(false);
    }
  };

  // Initialize voice session
  const initializeVoiceSession = async () => {
    console.log('initializeVoiceSession called');
    
    // Prevent multiple initializations
    if (sessionId) {
      console.log('Session already exists, skipping initialization');
      return;
    }
    
    try {
      console.log('Attempting to call backend API...');
      const response = await axios.post('/api/career-assessment/voice/initialize', {
        studentName: 'Student' // You could get this from user profile
      });
      console.log('Backend response:', response.data);
      setSessionId(response.data.sessionId);
      setConversationHistory([{
        role: 'assistant',
        content: response.data.welcomeMessage,
        timestamp: new Date()
      }]);
      
      console.log('About to call speakText with backend message...');
      // Speak the welcome message from backend
      speakText(response.data.welcomeMessage, response.data.sessionId);
      
      // Don't set a timeout here - let the speakText function handle when to start recording
      // The speakText function will call startRecordingWithSession after AI finishes speaking
    } catch (error) {
      console.error('Error initializing voice session:', error);
      console.log('Using fallback mock session...');
      // Fallback for when server is not running
      const mockSessionId = 'mock-session-' + Date.now();
      console.log('Using mock session ID:', mockSessionId);
      setSessionId(mockSessionId);
      const welcomeMessage = "Hi! I'm Alex, your AI career counselor. I'm here to help you discover your ideal career path. Let's start by talking about your interests and background. What would you like to tell me?";
      setConversationHistory([{
        role: 'assistant',
        content: welcomeMessage,
        timestamp: new Date()
      }]);
      
      console.log('About to call speakText with:', welcomeMessage);
      // Speak the welcome message
      speakText(welcomeMessage);
      
      console.log('Setting timeout to start recording in 3 seconds...');
      // Auto-start listening after welcome message
      setTimeout(() => {
        console.log('Timeout fired, starting recording...');
        if (mockSessionId) {
          startRecordingWithSession(mockSessionId);
        }
      }, 3000);
    }
  };

  // Start voice recording with real-time speech recognition
  const startRecordingWithSession = async (sessionIdParam) => {
    console.log('Starting recording with session...', { isListening, isAISpeaking, isPaused, sessionIdParam });
    try {
      if (isListening || isAISpeaking || isPaused) {
        console.log('Already listening, AI speaking, or session paused, returning');
        return; // Prevent multiple instances or continue if paused
      }
      
      // Use the provided session ID
      const currentSessionId = sessionIdParam;
      if (!currentSessionId) {
        console.log('No session ID provided, cannot start recording');
        return;
      }
      
      // Use Web Speech API for real-time transcription
      if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        console.log('Speech recognition supported, creating recognition object...');
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        
        recognition.continuous = false;
        recognition.interimResults = true;
        recognition.lang = 'en-US';
        
        recognition.onstart = () => {
          console.log('Speech recognition started');
          setIsRecording(true);
          setIsListening(true);
          setTranscription('');
          
          // Clear any previous recognition object
          if (window.recognition && window.recognition !== recognition) {
            try {
              window.recognition.stop();
            } catch (error) {
              console.log('Error stopping previous recognition:', error);
            }
          }
          window.recognition = recognition;
        };
        
        // Track transcript locally to avoid state timing issues
        let localTranscript = '';
        
        recognition.onresult = async (event) => {
          let interimTranscript = '';
          let finalTranscript = '';
          
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
              finalTranscript += transcript;
            } else {
              interimTranscript += transcript;
            }
          }
          
          const currentTranscript = finalTranscript || interimTranscript;
          localTranscript = currentTranscript; // Store locally
          setTranscription(currentTranscript);
          console.log('Speech recognition result:', currentTranscript);
        };
        
        recognition.onerror = (event) => {
          console.error('Speech recognition error:', event.error);
          setIsRecording(false);
          setIsListening(false);
          if (event.error === 'not-allowed') {
            alert('Microphone access denied. Please allow microphone permissions.');
          }
        };
        
        recognition.onend = async () => {
          console.log('Speech recognition ended, local transcript:', localTranscript);
          setIsRecording(false);
          setIsListening(false);
          
          // Use the local transcript that was captured during recognition
          const finalMessage = localTranscript.trim();
          console.log('Final message to send:', finalMessage);
          
          // Send the final transcript if we have one
          if (finalMessage) {
            await handleVoiceMessage(finalMessage, currentSessionId);
          } else {
            console.log('No transcript captured, not sending message');
          }
        };
        
        console.log('Starting speech recognition...');
        recognition.start();
        setMediaRecorder(recognition); // Store recognition object for stopping
        window.recognition = recognition; // Store globally for stopping during AI speech
      } else {
        // Fallback for browsers that don't support speech recognition
        console.error('Speech recognition not supported in this browser');
        alert('Speech recognition not supported in this browser. Please use a modern browser like Chrome.');
      }
    } catch (error) {
      console.error('Error starting recording:', error);
      alert('Could not access microphone. Please allow microphone permissions.');
    }
  };

  // Handle voice message (extracted from stopRecording)
  const handleVoiceMessage = async (message, sessionIdParam = null) => {
    const currentSessionId = sessionIdParam || sessionId;
    if (currentSessionId) {
      try {
        const response = await axios.post('/api/career-assessment/voice/chat', {
          sessionId: currentSessionId,
          message: message
        });
        
        setSessionPhase(response.data.sessionPhase);
        setConversationHistory(prev => [
          ...prev,
          { role: 'user', content: message, timestamp: new Date() },
          { role: 'assistant', content: response.data.response, timestamp: new Date() }
        ]);
        
        // Speak the AI response
        speakText(response.data.response, currentSessionId);
        
        // Clear transcription for next input
        setTranscription('');
      } catch (error) {
        console.error('Error sending message:', error);
        // Fallback for when server is not running
        const mockResponses = [
          "That's really interesting! Tell me more about your academic background. What subjects do you enjoy most in school?",
          "I see you're interested in technology. Have you taken any computer science or programming classes?",
          "Great! Now let's talk about your work style. Do you prefer working in teams or independently?",
          "That's helpful to know. What kind of environment do you see yourself working in - an office, outdoors, or something else?",
          "Excellent! Now let's explore your interests. What activities do you enjoy outside of school?",
          "I'm getting a good sense of your profile. What values are most important to you in a career?",
          "Perfect! Let's talk about your skills. What would you say are your strongest abilities?",
          "Thank you for sharing that. What are your biggest concerns about choosing a career path?",
          "I have a great understanding of your profile now. Let me generate some career recommendations for you!"
        ];
        
        const responseIndex = Math.min(conversationHistory.length / 2, mockResponses.length - 1);
        const mockResponse = mockResponses[responseIndex];
        
        setConversationHistory(prev => [
          ...prev,
          { role: 'user', content: message, timestamp: new Date() },
          { role: 'assistant', content: mockResponse, timestamp: new Date() }
        ]);
        
        // Speak the mock response
        speakText(mockResponse, currentSessionId);
        
        // Clear transcription for next input
        setTranscription('');
      }
    }
  };

  // Text-to-speech function
  const speakText = (text, sessionIdParam = null) => {
    console.log('speakText called with:', text);
    if ('speechSynthesis' in window) {
      console.log('Speech synthesis supported, creating utterance...');
      // Stop any current speech
      window.speechSynthesis.cancel();
      
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 0.9; // Slightly slower for clarity
      utterance.pitch = 1.0;
      utterance.volume = 1.0;
      
      // Try to use a more natural voice
      const voices = window.speechSynthesis.getVoices();
      const preferredVoice = voices.find(voice => 
        voice.name.includes('Alex') || 
        voice.name.includes('Samantha') || 
        voice.name.includes('Google') ||
        voice.name.includes('Natural')
      );
      if (preferredVoice) {
        utterance.voice = preferredVoice;
      }
      
      utterance.onstart = () => {
        setIsAISpeaking(true);
        console.log('AI started speaking:', text);
        
        // Stop any active speech recognition while AI speaks
        if (window.recognition) {
          console.log('Stopping speech recognition while AI speaks');
          try {
            window.recognition.stop();
            window.recognition = null; // Clear the reference
          } catch (error) {
            console.log('Error stopping recognition:', error);
          }
        }
      };
      
      utterance.onend = () => {
        setIsAISpeaking(false);
        console.log('AI finished speaking');
        // Only auto-start listening if not paused
        if (!isPaused) {
          setTimeout(() => {
            // Use the provided session ID or fall back to state
            const currentSessionId = sessionIdParam || sessionId;
            if (currentSessionId && !isListening && !isPaused) {
              console.log('Auto-starting listening after AI speech with session:', currentSessionId);
              startRecordingWithSession(currentSessionId);
            } else {
              console.log('Cannot start recording - no session ID, already listening, or paused');
            }
          }, 2000); // Increased delay to ensure AI speech is completely finished
        } else {
          console.log('Session is paused, not auto-starting listening');
        }
      };
      
      utterance.onerror = (event) => {
        console.error('Speech synthesis error:', event);
        setIsAISpeaking(false);
        // Don't restart recording on speech error - let the timeout handle it
      };
      
      window.speechSynthesis.speak(utterance);
    } else {
      console.warn('Speech synthesis not supported');
      // Fallback: just show the text and auto-start listening
      setIsAISpeaking(true);
      setTimeout(() => {
        setIsAISpeaking(false);
        if (sessionId && !isListening && !isPaused) {
          startRecordingWithSession(sessionId);
        }
      }, 2000);
    }
  };

  // Process audio recording with real-time transcription (fallback)
  const processAudioRecording = async (audioBlob) => {
    try {
      // Use Web Speech API for real-time transcription
      if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';
        
        recognition.onresult = async (event) => {
          const transcript = event.results[0][0].transcript;
          setTranscription(transcript);
          await handleVoiceMessage(transcript);
        };
        
        recognition.onerror = (event) => {
          console.error('Speech recognition error:', event.error);
          // Fallback to prompt if speech recognition fails
          const userInput = prompt("Speech recognition failed. What did you say?");
          if (userInput) {
            setTranscription(userInput);
            handleVoiceMessage(userInput);
          }
        };
        
        recognition.onend = () => {
          setIsRecording(false);
          setIsListening(false);
        };
        
        recognition.start();
      } else {
        // Fallback for browsers that don't support speech recognition
        const userInput = prompt("Speech recognition not supported. What did you say?");
        if (userInput) {
          setTranscription(userInput);
          await handleVoiceMessage(userInput);
        }
        setIsRecording(false);
        setIsListening(false);
      }
    } catch (error) {
      console.error('Error processing audio:', error);
      setIsRecording(false);
      setIsListening(false);
    }
  };

  // Stop voice recording
  const stopRecording = async () => {
    if (mediaRecorder && isRecording) {
      if (mediaRecorder.stop) {
        // MediaRecorder (fallback)
        mediaRecorder.stop();
        if (mediaRecorder.stream) {
          mediaRecorder.stream.getTracks().forEach(track => track.stop());
        }
      } else {
        // SpeechRecognition
        mediaRecorder.stop();
      }
    }
    setIsRecording(false);
    setIsListening(false);
  };

  // Complete voice session
  const completeVoiceSession = async () => {
    if (!sessionId) return;
    
    try {
      const response = await axios.post('/api/career-assessment/voice/complete', {
        sessionId: sessionId
      });
      
      navigate('/career-results', {
        state: {
          careerResults: {
            topMatches: response.data.careerMatches,
            sessionReport: response.data.sessionReport
          },
          assessmentData: formData
        }
      });
    } catch (error) {
      console.error('Error completing session:', error);
      // Fallback for when server is not running
              const finalMessage = "Perfect! I have a great understanding of your profile now. Let me generate some career recommendations for you. This will take just a moment...";
        
        // Speak the final message before showing results
        speakText(finalMessage);
        
        // Wait for speech to finish before navigating
        setTimeout(() => {
          const mockCareerResults = {
            topMatches: [
              {
                id: 'software_engineer',
                title: 'Software Engineer',
                category: 'Technology',
                description: 'Design, develop, and maintain software applications and systems',
                matchScore: 85,
                salary_range: { min: 70000, max: 150000 },
                growth_outlook: 'Excellent',
                education_required: 'bachelors',
                explanation: 'Your interest in technology and problem-solving makes this a great fit.',
                skillsGap: {
                  missingSkills: ['Advanced programming', 'System design', 'Cloud computing']
                }
              },
              {
                id: 'data_scientist',
                title: 'Data Scientist',
                category: 'Technology',
                description: 'Analyze complex data to help organizations make better decisions',
                matchScore: 78,
                salary_range: { min: 80000, max: 140000 },
                growth_outlook: 'Excellent',
                education_required: 'masters',
                explanation: 'Your analytical thinking and interest in patterns align well with this role.',
                skillsGap: {
                  missingSkills: ['Machine learning', 'Statistical analysis', 'Python programming']
                }
              }
            ],
            sessionReport: `Career Assessment Session Summary

Student Profile Analysis:
- Strong interest in technology and problem-solving
- Prefers analytical and structured work environments
- Values intellectual challenge and continuous learning
- Shows aptitude for logical thinking and attention to detail

Top Career Recommendations:
1. Software Engineer (85% match)
2. Data Scientist (78% match)

Next Steps:
- Consider pursuing computer science or related degree
- Develop programming skills in Python, JavaScript, or Java
- Gain experience through internships or personal projects
- Network with professionals in the tech industry`
          };
          
          navigate('/career-results', {
            state: {
              careerResults: mockCareerResults,
              assessmentData: formData
            }
          });
                }, 3000); // Wait 3 seconds for speech to complete
    }
  };

  // Render assessment type selection
  const renderAssessmentTypeSelection = () => (
    <div className="assessment-type-selection">
      <h1>Choose Your Career Assessment Method</h1>
      <p>Select how you'd like to discover your ideal career path</p>
      
      <div className="assessment-options">
        <div 
          className={`assessment-option ${assessmentType === 'form' ? 'selected' : ''}`}
          onClick={() => setAssessmentType('form')}
        >
          <div className="option-icon">
            <MessageCircle size={48} />
          </div>
          <h3>Traditional Assessment</h3>
          <p>Complete a comprehensive 100-question form covering all aspects of your personality, interests, and goals.</p>
          <ul>
            <li>✓ Detailed questions about your background</li>
            <li>✓ Work style and environment preferences</li>
            <li>✓ Skills and strengths assessment</li>
            <li>✓ Values and life priorities</li>
          </ul>
          <div className="option-duration">
            <Clock size={16} />
            <span>20-30 minutes</span>
          </div>
        </div>
        
        <div 
          className={`assessment-option ${assessmentType === 'voice' ? 'selected' : ''}`}
          onClick={() => setAssessmentType('voice')}
        >
          <div className="option-icon">
            <Mic size={48} />
          </div>
          <h3>AI Voice Counselor</h3>
          <p>Have a natural 45-minute conversation with Alex, our AI career counselor who adapts to your responses.</p>
          <ul>
            <li>✓ Natural conversation flow</li>
            <li>✓ Adaptive questioning based on your responses</li>
            <li>✓ Real-time insights and guidance</li>
            <li>✓ Comprehensive career analysis</li>
          </ul>
          <div className="option-duration">
            <Clock size={16} />
            <span>45 minutes</span>
          </div>
        </div>
      </div>
      
      {assessmentType && (
        <button 
          className="btn btn-primary btn-large"
          onClick={() => setCurrentStep(1)}
        >
          Continue with {assessmentType === 'form' ? 'Form Assessment' : 'Voice Counselor'}
          <ArrowRight size={20} />
        </button>
      )}
    </div>
  );

  // Render form assessment
  const renderFormAssessment = () => {
    if (!assessmentData) {
      return <div className="loading">Loading assessment questions...</div>;
    }

    const currentSection = assessmentData.sections[currentStep];
    
    return (
      <div className="form-assessment">
        <div className="assessment-header">
          <h2>Career Assessment - {currentSection.title}</h2>
          <p>{currentSection.description}</p>
          <div className="progress-bar">
            <div 
              className="progress-fill" 
              style={{ width: `${((currentStep + 1) / assessmentData.sections.length) * 100}%` }}
            />
          </div>
          <div className="progress-text">
            Step {currentStep + 1} of {assessmentData.sections.length}
          </div>
        </div>
        
        <div className="assessment-content">
          {currentSection.questions.map((question, index) => (
            <div key={question.id} className="question-container">
              <h3>{question.question}</h3>
              
              {question.type === 'select' && (
                <div className="question-options">
                  {question.options.map((option) => (
                    <label key={option.value} className="option">
                      <input 
                        type="radio" 
                        name={question.id} 
                        value={option.value}
                        checked={formData[question.id] === option.value}
                        onChange={(e) => handleInputChange(question.id, e.target.value)}
                      />
                      <span>{option.label}</span>
                    </label>
                  ))}
                </div>
              )}
              
              {question.type === 'multiselect' && (
                <div className="question-options">
                  {question.options.map((option) => (
                    <label key={option.value} className="option">
                      <input 
                        type="checkbox" 
                        value={option.value}
                        checked={formData[question.id]?.includes(option.value) || false}
                        onChange={(e) => handleMultiSelectChange(question.id, option.value, e.target.checked)}
                      />
                      <span>{option.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
        
        <div className="assessment-navigation">
          {currentStep > 0 && (
            <button 
              className="btn btn-secondary"
              onClick={() => setCurrentStep(currentStep - 1)}
            >
              <ArrowLeft size={20} />
              Previous
            </button>
          )}
          
          {currentStep < assessmentData.sections.length - 1 ? (
            <button 
              className="btn btn-primary"
              onClick={() => setCurrentStep(currentStep + 1)}
            >
              Next
              <ArrowRight size={20} />
            </button>
          ) : (
            <button 
              className="btn btn-primary"
              onClick={handleFormSubmit}
              disabled={loading}
            >
              {loading ? 'Processing...' : 'Get Career Recommendations'}
            </button>
          )}
        </div>
      </div>
    );
  };

  // Render voice counselor
  const renderVoiceCounselor = () => (
    <div className="voice-counselor-container">
      {/* Full-screen immersive interface */}
      <div className="voice-interface">
        {/* Background gradient */}
        <div className="voice-background">
          <div className="gradient-orb orb-1" />
          <div className="gradient-orb orb-2" />
          <div className="gradient-orb orb-3" />
        </div>

        {/* Main content area */}
        <div className="voice-content">
          {/* Top section with session info */}
          <div className="voice-header">
            <div className="session-info">
              <h2 className="counselor-title">
                <span className="counselor-icon">🤖</span>
                Alex - AI Career Counselor
              </h2>
              <div className="session-phase">Session Phase: {sessionPhase}</div>
            </div>
            
            <div className="session-controls">
              <button 
                onClick={handlePauseResume}
                className={`control-btn ${isPaused ? 'paused' : ''}`}
              >
                {isPaused ? 'Resume' : 'Pause'} Session
              </button>
              <button 
                onClick={completeVoiceSession}
                className="control-btn end-btn"
              >
                End Session & Get Results
              </button>
            </div>
          </div>

          {/* Center visualization area */}
          <div className="voice-center">
            {/* AI Speaking State */}
            {isAISpeaking && (
              <div className="ai-speaking-state">
                <div className="frequency-circle">
                  <AudioVisualizer isActive={true} type="speaking" />
                </div>
                <div className="state-text">Alex is speaking...</div>
              </div>
            )}

            {/* User Listening State */}
            {isListening && !isAISpeaking && (
              <div className="user-listening-state">
                <div className="microphone-circle">
                  <div className="mic-icon">🎤</div>
                  <div className="listening-ripple" />
                  <div className="listening-ripple" />
                  <div className="listening-ripple" />
                </div>
                <div className="state-text">Listening to you...</div>
                {transcription && (
                  <div className="transcription-display">
                    "{transcription}"
                  </div>
                )}
              </div>
            )}

            {/* Idle State */}
            {!isListening && !isAISpeaking && !isPaused && (
              <div className="idle-state">
                <div className="idle-circle">
                  <div className="idle-icon">💭</div>
                </div>
                <div className="state-text">Ready to begin...</div>
              </div>
            )}

            {/* Paused State */}
            {isPaused && (
              <div className="paused-state">
                <div className="paused-circle">
                  <div className="paused-icon">⏸️</div>
                </div>
                <div className="state-text">Session Paused</div>
                <div className="paused-message">Click "Resume Session" to continue</div>
              </div>
            )}
          </div>

          {/* Bottom tips */}
          <div className="voice-tips">
            <h3>Tips for a great session:</h3>
            <ul>
              <li>Speak naturally and be yourself</li>
              <li>Provide specific examples when possible</li>
              <li>Don't worry about perfect answers</li>
              <li>Feel free to ask questions</li>
            </ul>
          </div>
        </div>

        {/* Floating chat window */}
        <div className="floating-chat">
          <div className="chat-header">
            <h3>Conversation History</h3>
            <div className="chat-controls">
              <button 
                onClick={() => setChatMinimized(!chatMinimized)}
                className="minimize-btn"
              >
                {chatMinimized ? '📖' : '📕'}
              </button>
            </div>
          </div>
          
          {!chatMinimized && (
            <div className="chat-messages" ref={chatEndRef}>
              {conversationHistory.map((message, index) => (
                <div 
                  key={index} 
                  className={`chat-message ${message.role === 'assistant' ? 'ai' : 'user'}`}
                >
                  <div className="message-content">
                    {message.content}
                  </div>
                  <div className="message-time">
                    {message.timestamp.toLocaleTimeString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <style jsx="true">{`
        .career-assessment {
          max-width: 1200px;
          margin: 0 auto;
          padding: 2rem;
        }
        
        .assessment-type-selection {
          text-align: center;
          padding: 2rem 0;
        }
        
        .assessment-type-selection h1 {
          font-size: 2.5rem;
          margin-bottom: 1rem;
          color: #1f2937;
        }
        
        .assessment-type-selection p {
          font-size: 1.125rem;
          color: #6b7280;
          margin-bottom: 3rem;
        }
        
        .assessment-options {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 2rem;
          margin-bottom: 3rem;
        }
        
        .assessment-option {
          background: white;
          border: 2px solid #e5e7eb;
          border-radius: 1rem;
          padding: 2rem;
          cursor: pointer;
          transition: all 0.3s ease;
        }
        
        .assessment-option:hover {
          border-color: #3b82f6;
          transform: translateY(-2px);
        }
        
        .assessment-option.selected {
          border-color: #3b82f6;
          background: #f0f9ff;
        }
        
        .option-icon {
          color: #3b82f6;
          margin-bottom: 1rem;
        }
        
        .assessment-option h3 {
          font-size: 1.5rem;
          margin-bottom: 1rem;
          color: #1f2937;
        }
        
        .assessment-option p {
          color: #6b7280;
          margin-bottom: 1.5rem;
        }
        
        .assessment-option ul {
          text-align: left;
          margin-bottom: 1.5rem;
        }
        
        .assessment-option li {
          margin-bottom: 0.5rem;
          color: #374151;
        }
        
        .option-duration {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: #6b7280;
          font-size: 0.875rem;
        }
        
        .form-assessment {
          background: white;
          border-radius: 1rem;
          padding: 2rem;
          box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        .assessment-header {
          text-align: center;
          margin-bottom: 2rem;
        }
        
        .assessment-header h2 {
          font-size: 2rem;
          margin-bottom: 0.5rem;
          color: #1f2937;
        }
        
        .progress-bar {
          width: 100%;
          height: 8px;
          background: #e5e7eb;
          border-radius: 4px;
          margin: 1rem 0;
          overflow: hidden;
        }
        
        .progress-fill {
          height: 100%;
          background: linear-gradient(90deg, #3b82f6, #1d4ed8);
          transition: width 0.3s ease;
        }
        
        .progress-text {
          color: #6b7280;
          font-size: 0.875rem;
        }
        
        .question-container {
          margin-bottom: 2rem;
        }
        
        .question-container h3 {
          font-size: 1.25rem;
          margin-bottom: 1rem;
          color: #1f2937;
        }
        
        .question-options {
          display: flex;
          flex-direction: column;
          gap: 1rem;
        }
        
        .option {
          display: flex;
          align-items: center;
          gap: 0.75rem;
          padding: 1rem;
          border: 1px solid #e5e7eb;
          border-radius: 0.5rem;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        
        .option:hover {
          border-color: #3b82f6;
          background: #f0f9ff;
        }
        
        .assessment-navigation {
          display: flex;
          justify-content: space-between;
          margin-top: 2rem;
        }
        
        .voice-counselor-container {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: var(--bg-primary);
          z-index: 1000;
          overflow: hidden;
        }

        .voice-interface {
          position: relative;
          width: 100%;
          height: 100vh;
          display: flex;
          flex-direction: column;
        }

        .voice-background {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          z-index: -1;
          overflow: hidden;
        }

        .gradient-orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(60px);
          opacity: 0.2;
          animation: float 8s ease-in-out infinite;
        }

        .orb-1 {
          width: 500px;
          height: 500px;
          background: linear-gradient(45deg, var(--primary-color), var(--accent-color));
          top: 10%;
          right: 10%;
          animation-delay: 0s;
        }

        .orb-2 {
          width: 400px;
          height: 400px;
          background: linear-gradient(45deg, var(--accent-color), var(--success-color));
          bottom: 20%;
          left: 5%;
          animation-delay: 2s;
        }

        .orb-3 {
          width: 300px;
          height: 300px;
          background: linear-gradient(45deg, var(--success-color), var(--primary-color));
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          animation-delay: 4s;
        }

        @keyframes float {
          0%, 100% { transform: translateY(0px) scale(1); }
          50% { transform: translateY(-30px) scale(1.05); }
        }

        .voice-content {
          flex: 1;
          display: flex;
          flex-direction: column;
          padding: 2rem;
          max-width: 1200px;
          margin: 0 auto;
          width: 100%;
        }

        .voice-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 2rem;
        }

        .counselor-title {
          display: flex;
          align-items: center;
          gap: 1rem;
          font-size: 2rem;
          font-weight: 700;
          color: var(--text-primary);
          margin: 0;
        }

        .counselor-icon {
          font-size: 2.5rem;
        }

        .session-phase {
          color: var(--text-secondary);
          font-size: 1rem;
          margin-top: 0.5rem;
        }

        .session-controls {
          display: flex;
          gap: 1rem;
        }

        .control-btn {
          padding: 0.75rem 1.5rem;
          border: 1px solid var(--border-color);
          border-radius: 12px;
          background: var(--card-bg);
          color: var(--text-primary);
          font-weight: 600;
          cursor: pointer;
          transition: all 0.3s ease;
        }

        .control-btn:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 25px var(--shadow-color);
        }

        .control-btn.paused {
          background: var(--accent-color);
          color: white;
        }

        .end-btn {
          background: var(--error-color);
          color: white;
          border-color: var(--error-color);
        }

        .voice-center {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
        }

        .ai-speaking-state,
        .user-listening-state,
        .idle-state,
        .paused-state {
          text-align: center;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 2rem;
        }

        .frequency-circle,
        .microphone-circle,
        .idle-circle,
        .paused-circle {
          width: 200px;
          height: 200px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          position: relative;
          background: var(--card-bg);
          border: 2px solid var(--border-color);
          box-shadow: 0 20px 40px var(--shadow-color);
        }

        .frequency-circle {
          background: linear-gradient(135deg, var(--primary-color), var(--accent-color));
          border-color: var(--primary-color);
        }

        .microphone-circle {
          background: linear-gradient(135deg, var(--success-color), var(--accent-color));
          border-color: var(--success-color);
        }

        .mic-icon {
          font-size: 3rem;
          z-index: 2;
        }

        .listening-ripple {
          position: absolute;
          border: 2px solid var(--success-color);
          border-radius: 50%;
          animation: ripple 2s infinite;
        }

        .listening-ripple:nth-child(2) {
          animation-delay: 0.5s;
        }

        .listening-ripple:nth-child(3) {
          animation-delay: 1s;
        }

        @keyframes ripple {
          0% {
            width: 100px;
            height: 100px;
            opacity: 1;
          }
          100% {
            width: 300px;
            height: 300px;
            opacity: 0;
          }
        }

        .idle-icon {
          font-size: 3rem;
          opacity: 0.7;
        }

        .paused-circle {
          background: linear-gradient(135deg, var(--accent-color), var(--primary-color));
          border-color: var(--accent-color);
          animation: pulse 2s infinite;
        }

        .paused-icon {
          font-size: 3rem;
        }

        .paused-message {
          color: var(--text-secondary);
          font-size: 0.9rem;
          margin-top: 0.5rem;
        }

        @keyframes pulse {
          0% { transform: scale(1); }
          50% { transform: scale(1.05); }
          100% { transform: scale(1); }
        }

        .state-text {
          font-size: 1.5rem;
          font-weight: 600;
          color: var(--text-primary);
        }

        .transcription-display {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 12px;
          padding: 1rem 2rem;
          font-size: 1.1rem;
          color: var(--text-primary);
          max-width: 400px;
          box-shadow: 0 8px 25px var(--shadow-color);
        }

        .voice-tips {
          text-align: center;
          padding: 2rem;
          background: var(--card-bg);
          border-radius: 16px;
          border: 1px solid var(--border-color);
          margin-top: 2rem;
        }

        .voice-tips h3 {
          color: var(--text-primary);
          margin-bottom: 1rem;
        }

        .voice-tips ul {
          list-style: none;
          padding: 0;
          display: flex;
          justify-content: center;
          gap: 2rem;
          flex-wrap: wrap;
        }

        .voice-tips li {
          color: var(--text-secondary);
          font-size: 0.9rem;
        }

        .floating-chat {
          position: fixed;
          top: 2rem;
          right: 2rem;
          width: 350px;
          max-height: 500px;
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          box-shadow: 0 20px 40px var(--shadow-color);
          backdrop-filter: blur(10px);
          z-index: 1001;
          transition: all 0.3s ease;
        }

        .floating-chat:hover {
          transform: translateY(-5px);
          box-shadow: 0 30px 60px var(--shadow-color);
        }

        .chat-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 1rem 1.5rem;
          border-bottom: 1px solid var(--border-color);
        }

        .chat-header h3 {
          margin: 0;
          color: var(--text-primary);
          font-size: 1.1rem;
        }

        .minimize-btn {
          background: none;
          border: none;
          font-size: 1.2rem;
          cursor: pointer;
          padding: 0.5rem;
          border-radius: 8px;
          transition: all 0.2s ease;
        }

        .minimize-btn:hover {
          background: var(--bg-secondary);
        }

        .chat-messages {
          max-height: 400px;
          overflow-y: auto;
          padding: 1rem;
        }

        .chat-message {
          margin-bottom: 1rem;
          padding: 0.75rem 1rem;
          border-radius: 12px;
          max-width: 80%;
        }

        .chat-message.ai {
          background: var(--bg-secondary);
          margin-right: auto;
        }

        .chat-message.user {
          background: var(--primary-color);
          color: white;
          margin-left: auto;
        }

        .message-content {
          font-size: 0.9rem;
          line-height: 1.4;
        }

        .message-time {
          font-size: 0.7rem;
          opacity: 0.7;
          margin-top: 0.25rem;
        }

        @media (max-width: 768px) {
          .assessment-options {
            grid-template-columns: 1fr;
          }
          
          .conversation-container {
            grid-template-columns: 1fr;
          }
          
          .counselor-header {
            flex-direction: column;
            gap: 1rem;
            text-align: center;
          }

          .voice-header {
            flex-direction: column;
            gap: 1rem;
            text-align: center;
          }

          .session-controls {
            flex-direction: column;
            width: 100%;
          }

          .frequency-circle,
          .microphone-circle,
          .idle-circle {
            width: 150px;
            height: 150px;
          }

          .mic-icon,
          .idle-icon {
            font-size: 2rem;
          }

          .voice-tips ul {
            flex-direction: column;
            gap: 0.5rem;
          }

          .floating-chat {
            position: fixed;
            bottom: 1rem;
            right: 1rem;
            left: 1rem;
            width: auto;
            max-height: 300px;
          }
        }
      `}</style>
    </div>
  );

  return (
    <div className="career-assessment">
      {currentStep === 0 && renderAssessmentTypeSelection()}
      {currentStep === 1 && assessmentType === 'form' && renderFormAssessment()}
      {currentStep === 1 && assessmentType === 'voice' && renderVoiceCounselor()}
      
      <style jsx="true">{`
        .career-assessment {
          min-height: 100vh;
          padding: 2rem 0;
          background: var(--bg-primary);
          color: var(--text-primary);
        }
        
        .assessment-type-selection {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 2rem;
          text-align: center;
        }
        
        .assessment-type-selection h1 {
          font-size: 2.5rem;
          font-weight: 700;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }
        
        .assessment-type-selection p {
          font-size: 1.25rem;
          color: var(--text-secondary);
          margin-bottom: 3rem;
          line-height: 1.6;
        }
        
        .assessment-options {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
          gap: 2rem;
          margin-bottom: 3rem;
        }
        
        .assessment-option {
          background: var(--card-bg);
          border: 2px solid var(--border-color);
          border-radius: 20px;
          padding: 2.5rem;
          cursor: pointer;
          transition: all 0.3s ease;
          text-align: left;
          position: relative;
          overflow: hidden;
        }
        
        .assessment-option:hover {
          transform: translateY(-8px);
          box-shadow: 0 20px 40px var(--shadow-color);
          border-color: var(--primary-color);
        }
        
        .assessment-option.selected {
          border-color: var(--primary-color);
          box-shadow: 0 0 0 3px var(--primary-color-alpha);
          background: var(--bg-secondary);
        }
        
        .option-icon {
          width: 80px;
          height: 80px;
          background: linear-gradient(135deg, var(--primary-color), var(--accent-color));
          border-radius: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          margin-bottom: 1.5rem;
          color: white;
        }
        
        .assessment-option h3 {
          font-size: 1.75rem;
          font-weight: 700;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }
        
        .assessment-option p {
          color: var(--text-secondary);
          line-height: 1.6;
          margin-bottom: 1.5rem;
          font-size: 1.1rem;
        }
        
        .assessment-option ul {
          list-style: none;
          padding: 0;
          margin-bottom: 1.5rem;
        }
        
        .assessment-option li {
          color: var(--text-secondary);
          margin-bottom: 0.5rem;
          font-size: 1rem;
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        
        .option-duration {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          color: var(--text-secondary);
          font-weight: 500;
          font-size: 0.9rem;
        }
        
        .btn-large {
          padding: 1rem 2rem;
          font-size: 1.1rem;
          font-weight: 600;
          display: inline-flex;
          align-items: center;
          gap: 0.5rem;
          margin-top: 1rem;
        }
        
        .form-container {
          max-width: 800px;
          margin: 0 auto;
        }
        
        .form-section {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          margin-bottom: 2rem;
        }
        
        .form-section h3 {
          color: var(--text-primary);
          margin-bottom: 1.5rem;
          font-size: 1.25rem;
        }
        
        .form-group {
          margin-bottom: 1.5rem;
        }
        
        .form-label {
          display: block;
          margin-bottom: 0.5rem;
          font-weight: 500;
          color: var(--text-primary);
        }
        
        .form-input,
        .form-select,
        .form-textarea {
          width: 100%;
          padding: 0.75rem;
          border: 1px solid var(--input-border);
          border-radius: 8px;
          background: var(--input-bg);
          color: var(--text-primary);
          font-size: 1rem;
          transition: all 0.2s ease;
        }
        
        .form-input:focus,
        .form-select:focus,
        .form-textarea:focus {
          outline: none;
          border-color: var(--primary-color);
          box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
        }
        
        .form-textarea {
          min-height: 100px;
          resize: vertical;
        }
        
        .checkbox-group {
          display: flex;
          flex-wrap: wrap;
          gap: 1rem;
        }
        
        .checkbox-item {
          display: flex;
          align-items: center;
          gap: 0.5rem;
        }
        
        .checkbox-item input[type="checkbox"] {
          width: auto;
        }
        
        .form-actions {
          display: flex;
          gap: 1rem;
          justify-content: center;
          margin-top: 2rem;
        }
        
        .loading {
          text-align: center;
          padding: 3rem;
          font-size: 1.125rem;
          color: var(--text-secondary);
        }
        
        .form-assessment {
          max-width: 800px;
          margin: 0 auto;
          padding: 0 2rem;
        }
        
        .assessment-header {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          margin-bottom: 2rem;
          text-align: center;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .assessment-header h2 {
          font-size: 2rem;
          font-weight: 700;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }
        
        .assessment-header p {
          color: var(--text-secondary);
          margin-bottom: 1.5rem;
          font-size: 1.1rem;
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
          color: var(--text-secondary);
          font-weight: 600;
        }
        
        .assessment-content {
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          padding: 2rem;
          box-shadow: 0 4px 6px var(--shadow-color);
        }
        
        .question-container {
          margin-bottom: 2rem;
        }
        
        .question-container h3 {
          font-size: 1.25rem;
          font-weight: 600;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }
        
        .question-options {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }
        
        .option {
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
        
        .option:hover {
          border-color: var(--primary-color);
          background: var(--bg-secondary);
          transform: translateY(-2px);
          box-shadow: 0 4px 12px var(--shadow-color);
        }
        
        .option input[type="radio"] {
          margin-top: 0.25rem;
        }
        
        .option span {
          flex: 1;
          color: var(--text-primary);
          font-weight: 500;
          line-height: 1.5;
        }
        
        @media (max-width: 768px) {
          .career-assessment {
            padding: 1rem 0;
          }
          
          .assessment-type-selection {
            padding: 0 1rem;
          }
          
          .assessment-type-selection h1 {
            font-size: 2rem;
          }
          
          .assessment-options {
            grid-template-columns: 1fr;
            gap: 1.5rem;
          }
          
          .assessment-option {
            padding: 2rem;
          }
          
          .form-assessment {
            padding: 0 1rem;
          }
          
          .assessment-header,
          .assessment-content {
            padding: 1.5rem;
          }
          
          .form-actions {
            flex-direction: column;
          }
        }
      `}</style>
    </div>
  );
};

export default CareerAssessment; 