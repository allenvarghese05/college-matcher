// AI Voice Counselor Service
// Uses OpenAI GPT-4 for natural conversation and career guidance

const OpenAI = require('openai');

class AICounselor {
  constructor() {
    this.openai = new OpenAI({ 
      apiKey: process.env.OPENAI_API_KEY 
    });
    this.sessionState = new Map();
    this.conversationHistory = new Map();
  }

  // Initialize a new counseling session
  initializeSession(sessionId, studentName) {
    const session = {
      id: sessionId,
      studentName: studentName,
      startTime: new Date(),
      currentPhase: 'introduction',
      extractedData: {},
      conversationLog: [],
      insights: [],
      recommendations: []
    };
    
    this.sessionState.set(sessionId, session);
    this.conversationHistory.set(sessionId, []);
    
    return session;
  }

  // Generate AI counselor response
  async generateResponse(sessionId, userInput, audioTranscription = null) {
    const session = this.sessionState.get(sessionId);
    if (!session) {
      throw new Error('Session not found');
    }

    // Add user input to conversation history
    const userMessage = {
      role: 'user',
      content: audioTranscription || userInput,
      timestamp: new Date()
    };
    
    session.conversationLog.push(userMessage);
    this.conversationHistory.get(sessionId).push(userMessage);

    try {
      // Build conversation context
      const conversationContext = this.buildConversationContext(sessionId);
      
      // Create system prompt
      const systemPrompt = this.createSystemPrompt(session);
      
      // Call OpenAI API
      const completion = await this.openai.chat.completions.create({
        model: "gpt-4",
        messages: [
          { role: "system", content: systemPrompt },
          ...conversationContext
        ],
        max_tokens: 300,
        temperature: 0.7
      });

      const aiResponse = completion.choices[0].message.content;
      
      // Add AI response to conversation history
      const assistantMessage = {
        role: 'assistant',
        content: aiResponse,
        timestamp: new Date()
      };
      
      session.conversationLog.push(assistantMessage);
      this.conversationHistory.get(sessionId).push(assistantMessage);

      // Extract insights from the conversation
      await this.extractInsights(sessionId, userInput, aiResponse);
      
      // Update session phase based on conversation progress
      this.updateSessionPhase(sessionId);

      return {
        response: aiResponse,
        sessionPhase: session.currentPhase,
        extractedData: session.extractedData,
        insights: session.insights
      };
    } catch (error) {
      console.error('OpenAI API Error:', error);
      throw new Error('Failed to generate AI response');
    }
  }

  // Create system prompt for the AI counselor
  createSystemPrompt(session) {
    return `You are Alex, an AI career counselor conducting a 45-minute career assessment session with ${session.studentName}. 

Your role is to:
1. Conduct a natural, conversational career assessment
2. Ask thoughtful follow-up questions based on responses
3. Extract key information about interests, skills, values, and goals
4. Provide encouraging and supportive guidance
5. Maintain a warm, professional tone

Current session phase: ${session.currentPhase}

Assessment structure:
- Introduction (5 minutes): Build rapport and explain the process
- Academic Background (10 minutes): Explore educational experiences and preferences
- Work Style & Environment (10 minutes): Understand work preferences and personality
- Interests & Activities (10 minutes): Discover passions and hobbies
- Values & Life Priorities (5 minutes): Identify core values and motivations
- Skills & Strengths (5 minutes): Assess current abilities and potential

Guidelines:
- Ask one question at a time
- Listen actively and build on previous responses
- Use natural conversation flow, not rigid questioning
- Extract specific data points for career matching
- Be encouraging and supportive
- Keep responses concise but engaging
- Adapt your approach based on the student's communication style

Remember: This is a conversation, not an interrogation. Make the student feel comfortable and heard.`;
  }

  // Build conversation context for AI
  buildConversationContext(sessionId) {
    const history = this.conversationHistory.get(sessionId) || [];
    const recentMessages = history.slice(-10); // Last 10 messages for context
    
    return recentMessages.map(msg => ({
      role: msg.role,
      content: msg.content
    }));
  }

  // Extract insights from conversation
  async extractInsights(sessionId, userInput, aiResponse) {
    const session = this.sessionState.get(sessionId);
    
    // Mock insight extraction for MVP
    const mockInsights = {
      academic_interests: ['technology', 'science'],
      work_style: ['team', 'independent'],
      personal_interests: ['problem_solving', 'creativity'],
      values: ['intellectual_challenge', 'helping_others'],
      skills: ['analytical_thinking', 'communication'],
      career_goals: ['technology_field', 'innovation']
    };
    
    // Merge with existing extracted data
    session.extractedData = { ...session.extractedData, ...mockInsights };
    
    // Add insight to session
    session.insights.push({
      timestamp: new Date(),
      userInput: userInput,
      extractedData: mockInsights
    });
  }

  // Update session phase based on conversation progress
  updateSessionPhase(sessionId) {
    const session = this.sessionState.get(sessionId);
    const conversationLength = session.conversationLog.length;
    
    // Simple phase progression based on conversation length
    if (conversationLength < 4) {
      session.currentPhase = 'introduction';
    } else if (conversationLength < 12) {
      session.currentPhase = 'academic_background';
    } else if (conversationLength < 20) {
      session.currentPhase = 'work_style';
    } else if (conversationLength < 28) {
      session.currentPhase = 'interests_activities';
    } else if (conversationLength < 36) {
      session.currentPhase = 'values_priorities';
    } else if (conversationLength < 44) {
      session.currentPhase = 'skills_strengths';
    } else {
      session.currentPhase = 'conclusion';
    }
  }

  // Generate career recommendations based on session data
  async generateCareerRecommendations(sessionId) {
    const session = this.sessionState.get(sessionId);
    
    // Mock career recommendations for MVP
    const mockRecommendations = {
      top_careers: [
        {
          title: "Software Engineer",
          match_score: 95,
          explanation: "Strong alignment with your technical interests and problem-solving skills",
          skills_gap: ["Programming languages", "Software development methodologies"],
          education_pathway: "Bachelor's in Computer Science"
        },
        {
          title: "Data Scientist",
          match_score: 88,
          explanation: "Excellent fit for your analytical thinking and interest in technology",
          skills_gap: ["Statistical analysis", "Machine learning"],
          education_pathway: "Bachelor's in Data Science or Statistics"
        },
        {
          title: "Product Manager",
          match_score: 82,
          explanation: "Great match for your leadership potential and technical understanding",
          skills_gap: ["Business strategy", "User experience design"],
          education_pathway: "Bachelor's in Business or Computer Science"
        }
      ],
      skills_gap_analysis: {
        technical_skills: ["Programming", "Data analysis", "Project management"],
        soft_skills: ["Leadership", "Communication", "Strategic thinking"]
      },
      educational_pathways: [
        "Computer Science degree with business minor",
        "Data Science degree with focus on applications",
        "Business degree with technology concentration"
      ],
      next_steps: [
        "Take introductory programming courses",
        "Join technology clubs and hackathons",
        "Seek internships in tech companies",
        "Build a portfolio of technical projects"
      ]
    };
    
    if (session) {
      session.recommendations = mockRecommendations;
    }
    return mockRecommendations;
  }

  // Generate session summary and report
  async generateSessionReport(sessionId) {
    const session = this.sessionState.get(sessionId);
    
    // Mock session report for MVP
    const mockReport = `
# Career Assessment Report

## Executive Summary
Based on our 45-minute career counseling session, I've identified strong alignment with technology and analytical fields. Your profile shows excellent potential for careers in software development, data science, and technology management.

## Key Insights
- **Academic Strengths**: Strong performance in mathematics and science
- **Work Style**: Comfortable with both team collaboration and independent work
- **Interests**: Technology, problem-solving, and creative solutions
- **Values**: Intellectual challenge, helping others, and innovation
- **Skills**: Analytical thinking, communication, and leadership potential

## Top Career Recommendations
1. **Software Engineer** (95% match)
   - Strong alignment with technical interests
   - Excellent problem-solving skills
   - High demand and growth potential

2. **Data Scientist** (88% match)
   - Perfect for analytical thinking
   - Combines technology and business impact
   - Rapidly growing field

3. **Product Manager** (82% match)
   - Leverages technical understanding and leadership
   - Strategic role in technology companies
   - High impact and responsibility

## Skills Gap Analysis
**Technical Skills to Develop:**
- Programming languages (Python, JavaScript)
- Software development methodologies
- Data analysis and visualization

**Soft Skills to Enhance:**
- Project management
- Strategic thinking
- User experience design

## Educational Pathway Recommendations
- **Primary**: Bachelor's in Computer Science
- **Alternative**: Data Science degree with business focus
- **Complementary**: Business minor or concentration

## Action Plan
1. Take introductory programming courses
2. Join technology clubs and hackathons
3. Seek internships in tech companies
4. Build a portfolio of technical projects
5. Network with professionals in target fields

## Next Steps
- Research specific companies and roles
- Connect with alumni in target careers
- Develop technical skills through online courses
- Attend career fairs and networking events

This assessment provides a solid foundation for your career exploration journey. Focus on building both technical and soft skills while gaining practical experience through projects and internships.
    `;
    
    return mockReport;
  }

  // Pause and resume session functionality
  pauseSession(sessionId) {
    const session = this.sessionState.get(sessionId);
    if (session) {
      session.paused = true;
      session.pauseTime = new Date();
    }
  }

  resumeSession(sessionId) {
    const session = this.sessionState.get(sessionId);
    if (session) {
      session.paused = false;
      session.resumeTime = new Date();
    }
  }

  // Get session status
  getSessionStatus(sessionId) {
    const session = this.sessionState.get(sessionId);
    if (!session) return null;
    
    return {
      id: session.id,
      studentName: session.studentName,
      currentPhase: session.currentPhase,
      startTime: session.startTime,
      duration: new Date() - session.startTime,
      paused: session.paused || false,
      extractedData: session.extractedData,
      insights: session.insights.length,
      recommendations: session.recommendations.length > 0
    };
  }

  // Clean up session data
  cleanupSession(sessionId) {
    this.sessionState.delete(sessionId);
    this.conversationHistory.delete(sessionId);
  }
}

module.exports = AICounselor; 