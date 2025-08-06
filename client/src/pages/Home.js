import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, GraduationCap, Brain, Search, BarChart3, Sparkles, Users, Award } from 'lucide-react';
import { useTheme } from '../App';

const Home = () => {
  const { isDarkMode } = useTheme();
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });

  useEffect(() => {
    const handleMouseMove = (e) => {
      setMousePosition({ x: e.clientX, y: e.clientY });
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  const features = [
    {
      icon: <BarChart3 size={32} />,
      title: "Smart College Matching",
      description: "AI-powered algorithm matches you with the perfect colleges based on your academic profile, preferences, and goals.",
      color: "from-blue-500 to-cyan-500"
    },
    {
      icon: <Brain size={32} />,
      title: "AI Career Counselor",
      description: "Interactive voice sessions with Alex, our AI career counselor, to discover your ideal career path.",
      color: "from-purple-500 to-pink-500"
    },
    {
      icon: <Search size={32} />,
      title: "Comprehensive School Database",
      description: "Browse detailed profiles of thousands of colleges with real student reviews and insights.",
      color: "from-green-500 to-emerald-500"
    }
  ];

  const stats = [
    { number: "500+", label: "Colleges", icon: <GraduationCap size={24} /> },
    { number: "10K+", label: "Students", icon: <Users size={24} /> },
    { number: "95%", label: "Success Rate", icon: <Award size={24} /> },
    { number: "24/7", label: "AI Support", icon: <Sparkles size={24} /> }
  ];

  return (
    <div className="home">
      {/* Hero Section */}
      <section className="hero">
        <div className="hero-background">
          <div 
            className="floating-orb orb-1"
            style={{
              transform: `translate(${mousePosition.x * 0.02}px, ${mousePosition.y * 0.02}px)`
            }}
          />
          <div 
            className="floating-orb orb-2"
            style={{
              transform: `translate(${mousePosition.x * -0.01}px, ${mousePosition.y * -0.01}px)`
            }}
          />
        </div>
        
        <div className="hero-content">
          <div className="hero-text">
            <h1 className="hero-title">
              Find Your Perfect
              <span className="gradient-text"> College Match</span>
            </h1>
            <p className="hero-description">
              Discover the ideal college for your academic journey with our AI-powered matching system. 
              Get personalized recommendations based on your unique profile and aspirations.
            </p>
            <div className="hero-actions">
              <Link to="/assessment" className="btn btn-primary btn-large">
                Start Assessment
                <ArrowRight size={20} />
              </Link>
              <Link to="/career-assessment" className="btn btn-secondary btn-large">
                AI Career Counselor
                <Brain size={20} />
              </Link>
            </div>
          </div>
          
          <div className="hero-visual">
            <div className="floating-card card-1">
              <GraduationCap size={48} />
              <h3>Smart Matching</h3>
            </div>
            <div className="floating-card card-2">
              <Brain size={48} />
              <h3>AI Guidance</h3>
            </div>
            <div className="floating-card card-3">
              <Search size={48} />
              <h3>Discover</h3>
            </div>
          </div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="stats-section">
        <div className="stats-grid">
          {stats.map((stat, index) => (
            <div key={index} className="stat-card">
              <div className="stat-icon">{stat.icon}</div>
              <div className="stat-number">{stat.number}</div>
              <div className="stat-label">{stat.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Features Section */}
      <section className="features-section">
        <h2 className="section-title">Why Choose College Matcher?</h2>
        <div className="features-grid">
          {features.map((feature, index) => (
            <div key={index} className="feature-card">
              <div className={`feature-icon bg-gradient-to-r ${feature.color}`}>
                {feature.icon}
              </div>
              <h3 className="feature-title">{feature.title}</h3>
              <p className="feature-description">{feature.description}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="cta-content">
          <h2>Ready to Find Your Perfect College?</h2>
          <p>Join thousands of students who have discovered their ideal academic path.</p>
          <Link to="/assessment" className="btn btn-primary btn-large">
            Get Started Now
            <ArrowRight size={20} />
          </Link>
        </div>
      </section>

      <style jsx="true">{`
        .home {
          min-height: 100vh;
          overflow-x: hidden;
        }

        .hero {
          position: relative;
          min-height: 100vh;
          display: flex;
          align-items: center;
          padding: 2rem 0;
          overflow: hidden;
        }

        .hero-background {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          z-index: -1;
        }

        .floating-orb {
          position: absolute;
          border-radius: 50%;
          filter: blur(40px);
          opacity: 0.3;
          transition: transform 0.1s ease;
        }

        .orb-1 {
          width: 400px;
          height: 400px;
          background: linear-gradient(45deg, var(--primary-color), var(--accent-color));
          top: 10%;
          right: 10%;
        }

        .orb-2 {
          width: 300px;
          height: 300px;
          background: linear-gradient(45deg, var(--accent-color), var(--success-color));
          bottom: 20%;
          left: 5%;
        }

        .hero-content {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 2rem;
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 4rem;
          align-items: center;
        }

        .hero-title {
          font-size: 3.5rem;
          font-weight: 800;
          line-height: 1.1;
          margin-bottom: 1.5rem;
          color: var(--text-primary);
        }

        .gradient-text {
          background: linear-gradient(135deg, var(--primary-color), var(--accent-color));
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
        }

        .hero-description {
          font-size: 1.25rem;
          color: var(--text-secondary);
          margin-bottom: 2rem;
          line-height: 1.6;
        }

        .hero-actions {
          display: flex;
          gap: 1rem;
          flex-wrap: wrap;
        }

        .btn-large {
          padding: 1rem 2rem;
          font-size: 1.1rem;
          font-weight: 600;
        }

        .hero-visual {
          position: relative;
          height: 500px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .floating-card {
          position: absolute;
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 20px;
          padding: 2rem;
          text-align: center;
          box-shadow: 0 20px 40px var(--shadow-color);
          backdrop-filter: blur(10px);
          transition: all 0.3s ease;
          animation: float 6s ease-in-out infinite;
        }

        .floating-card:hover {
          transform: translateY(-10px) scale(1.05);
          box-shadow: 0 30px 60px var(--shadow-color);
        }

        .card-1 {
          top: 20%;
          left: 10%;
          animation-delay: 0s;
        }

        .card-2 {
          top: 50%;
          right: 10%;
          animation-delay: 2s;
        }

        .card-3 {
          bottom: 20%;
          left: 20%;
          animation-delay: 4s;
        }

        @keyframes float {
          0%, 100% { transform: translateY(0px); }
          50% { transform: translateY(-20px); }
        }

        .stats-section {
          padding: 4rem 0;
          background: var(--bg-secondary);
        }

        .stats-grid {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 2rem;
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
          gap: 2rem;
        }

        .stat-card {
          text-align: center;
          padding: 2rem;
          background: var(--card-bg);
          border-radius: 16px;
          border: 1px solid var(--border-color);
          transition: all 0.3s ease;
        }

        .stat-card:hover {
          transform: translateY(-5px);
          box-shadow: 0 10px 30px var(--shadow-color);
        }

        .stat-icon {
          color: var(--primary-color);
          margin-bottom: 1rem;
        }

        .stat-number {
          font-size: 2.5rem;
          font-weight: 800;
          color: var(--text-primary);
          margin-bottom: 0.5rem;
        }

        .stat-label {
          color: var(--text-secondary);
          font-weight: 500;
        }

        .features-section {
          padding: 6rem 0;
          max-width: 1200px;
          margin: 0 auto;
          padding-left: 2rem;
          padding-right: 2rem;
        }

        .section-title {
          text-align: center;
          font-size: 2.5rem;
          font-weight: 700;
          margin-bottom: 3rem;
          color: var(--text-primary);
        }

        .features-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 2rem;
        }

        .feature-card {
          padding: 2rem;
          background: var(--card-bg);
          border: 1px solid var(--border-color);
          border-radius: 16px;
          text-align: center;
          transition: all 0.3s ease;
        }

        .feature-card:hover {
          transform: translateY(-5px);
          box-shadow: 0 20px 40px var(--shadow-color);
        }

        .feature-icon {
          width: 80px;
          height: 80px;
          border-radius: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          margin: 0 auto 1.5rem;
          color: white;
        }

        .feature-title {
          font-size: 1.5rem;
          font-weight: 600;
          margin-bottom: 1rem;
          color: var(--text-primary);
        }

        .feature-description {
          color: var(--text-secondary);
          line-height: 1.6;
        }

        .cta-section {
          padding: 6rem 0;
          background: linear-gradient(135deg, var(--primary-color), var(--accent-color));
          text-align: center;
          color: white;
        }

        .cta-content {
          max-width: 600px;
          margin: 0 auto;
          padding: 0 2rem;
        }

        .cta-content h2 {
          font-size: 2.5rem;
          font-weight: 700;
          margin-bottom: 1rem;
        }

        .cta-content p {
          font-size: 1.25rem;
          margin-bottom: 2rem;
          opacity: 0.9;
        }

        @media (max-width: 768px) {
          .hero-content {
            grid-template-columns: 1fr;
            gap: 2rem;
            text-align: center;
          }

          .hero-title {
            font-size: 2.5rem;
          }

          .hero-actions {
            justify-content: center;
          }

          .floating-card {
            position: relative;
            margin: 1rem;
            animation: none;
          }

          .hero-visual {
            height: auto;
            flex-direction: column;
          }

          .stats-grid {
            grid-template-columns: repeat(2, 1fr);
          }

          .features-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </div>
  );
};

export default Home; 