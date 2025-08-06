# 🎓 College Matcher - AI-Powered College & Career Discovery Platform

A modern web application that helps students discover their ideal colleges and career paths using AI-powered assessments, voice interactions, and intelligent matching algorithms.

## ✨ Features

### 🏠 **Home Page**

- Modern, responsive landing page with gradient backgrounds
- Interactive statistics and feature highlights
- Dark/light theme support
- Call-to-action sections for different assessment types

### 🎯 **College Assessment**

- **Multi-step form assessment** with comprehensive questions
- **AI Voice Counselor** with real-time speech recognition
- **Pause/Resume functionality** for voice sessions
- **Progress tracking** with visual indicators
- **Smart question flow** based on user responses

### 🎤 **AI Voice Counselor**

- **Real-time speech recognition** using Web Speech API
- **Natural language processing** for conversation flow
- **Visual feedback** with audio visualizations
- **Session management** with pause/resume controls
- **Conversation history** tracking

### 🏫 **Browse Schools**

- **Comprehensive school database** with detailed information
- **Advanced filtering** by location, programs, size, etc.
- **Search functionality** with real-time results
- **School cards** with key statistics and programs
- **Responsive grid layout** for all screen sizes

### 📊 **Results & Matching**

- **Intelligent matching algorithm** based on assessment data
- **Personalized recommendations** with match percentages
- **Detailed school profiles** with admission requirements
- **Career path suggestions** with salary and growth data
- **Export/share functionality** for results

### 🎨 **Modern UI/UX**

- **Consistent design system** across all pages
- **Dark/light theme** with automatic detection
- **Responsive design** for mobile, tablet, and desktop
- **Smooth animations** and transitions
- **Accessibility features** for all users

## 🛠️ Technology Stack

### **Frontend**

- **React 18** - Modern UI framework
- **React Router** - Client-side routing
- **CSS-in-JS** - Component-scoped styling
- **Web Speech API** - Voice recognition and synthesis
- **Axios** - HTTP client for API calls

### **Backend**

- **Node.js** - Server runtime
- **Express.js** - Web framework
- **MongoDB** - Database (optional)
- **JWT** - Authentication (planned)
- **Multer** - File uploads

### **AI & ML**

- **OpenAI API** - Natural language processing
- **Custom matching algorithms** - College and career recommendations
- **Speech-to-text** - Real-time transcription
- **Text-to-speech** - AI voice responses

## 🚀 Quick Start

### Prerequisites

- Node.js (v16 or higher)
- npm or yarn
- Modern browser with Web Speech API support

### Installation

1. **Clone the repository**

   ```bash
   git clone <your-repo-url>
   cd college-matcher
   ```

2. **Install dependencies**

   ```bash
   npm install
   ```

3. **Set up environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

4. **Start the development servers**

   ```bash
   npm run dev
   ```

5. **Open your browser**
   - Frontend: http://localhost:3000
   - Backend: http://localhost:5001

## 📁 Project Structure

```
college-matcher/
├── client/                 # React frontend
│   ├── public/            # Static assets
│   ├── src/
│   │   ├── components/    # Reusable components
│   │   ├── pages/         # Page components
│   │   ├── App.js         # Main app component
│   │   └── index.js       # Entry point
│   └── package.json
├── server/                # Express backend
│   ├── routes/           # API routes
│   ├── models/           # Data models
│   ├── middleware/       # Custom middleware
│   ├── index.js          # Server entry point
│   └── package.json
├── package.json          # Root package.json
└── README.md
```

## 🎯 Key Features Explained

### **AI Voice Counselor**

The voice counselor uses advanced speech recognition and synthesis to create a natural conversation experience:

- **Real-time transcription** of user speech
- **Context-aware responses** based on conversation history
- **Visual feedback** with audio visualizations
- **Session management** with pause/resume functionality
- **Fallback support** for browsers without speech API

### **Intelligent Matching Algorithm**

Our matching system considers multiple factors:

- **Academic profile** (GPA, test scores, course rigor)
- **Interests and activities** (extracurriculars, hobbies)
- **Career goals** (desired salary, work environment)
- **Geographic preferences** (location, climate, urban/rural)
- **Financial considerations** (budget, financial aid needs)

### **Responsive Design System**

Built with modern CSS practices:

- **CSS Variables** for consistent theming
- **Flexbox and Grid** for responsive layouts
- **Mobile-first approach** for all components
- **Smooth animations** and micro-interactions
- **Accessibility compliance** (WCAG 2.1)

## 🔧 Development

### **Available Scripts**

```bash
npm run dev          # Start both frontend and backend
npm run client       # Start only frontend
npm run server       # Start only backend
npm run build        # Build for production
npm run test         # Run tests
npm run lint         # Lint code
```

### **Code Style**

- **ESLint** for JavaScript linting
- **Prettier** for code formatting
- **Component-based architecture**
- **Consistent naming conventions**

## 🚀 Deployment

### **Frontend (Vercel/Netlify)**

```bash
npm run build
# Deploy the client/build folder
```

### **Backend (Heroku/Railway)**

```bash
# Set environment variables
# Deploy server folder
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **OpenAI** for AI capabilities
- **Web Speech API** for voice features
- **React community** for excellent documentation
- **Express.js** for robust backend framework

## 📞 Support

For support, email support@collegematcher.com or create an issue in this repository.

---

**Built with ❤️ for students discovering their future**
