// Advanced College Matching Algorithm v2.1
// Enhanced with improved UX features and refined scoring logic

class CollegeMatchingAlgorithm {
  constructor() {
    // Updated scoring weights based on research
    this.scoringWeights = {
      academic: 50,      // Academic fit is #1 predictor of success
      financial: 20,     // Important but not dominant
      personality: 15,   // Matters but was over-weighted before
      locationSize: 10,  // Location and size preferences
      extracurricular: 5 // Nice to have but not critical
    };

    // Personality compatibility matrix (based on MBTI and Big Five research)
    this.personalityCompatibility = {
      analytical: {
        analytical: 1.0, ambitious: 0.8, balanced: 0.7, progressive: 0.6, creative: 0.4, social: 0.3
      },
      creative: {
        creative: 1.0, progressive: 0.9, balanced: 0.7, social: 0.6, analytical: 0.4, ambitious: 0.3
      },
      social: {
        social: 1.0, balanced: 0.8, progressive: 0.7, creative: 0.6, ambitious: 0.5, analytical: 0.3
      },
      ambitious: {
        ambitious: 1.0, analytical: 0.8, balanced: 0.7, social: 0.5, progressive: 0.4, creative: 0.3
      },
      balanced: {
        balanced: 1.0, social: 0.8, analytical: 0.7, ambitious: 0.7, progressive: 0.6, creative: 0.7
      },
      progressive: {
        progressive: 1.0, creative: 0.9, social: 0.7, balanced: 0.6, analytical: 0.6, ambitious: 0.4
      }
    };

    // School-specific program strength (major-specific weighting)
    this.schoolProgramStrength = {
      // Computer Science
      'Computer Science': {
        'MIT': 1.0, 'Stanford': 1.0, 'UC Berkeley': 0.95, 'CMU': 0.95,
        'University of Michigan': 0.85, 'UT Austin': 0.8, 'University of Washington': 0.8,
        'University of Florida': 0.6, 'University of North Carolina': 0.7,
        'New York University': 0.75, 'Harvard': 0.8
      },
      // Engineering
      'Engineering': {
        'MIT': 1.0, 'Stanford': 0.95, 'UC Berkeley': 0.95, 'CMU': 0.9,
        'University of Michigan': 0.9, 'UT Austin': 0.85, 'University of Washington': 0.8,
        'University of Florida': 0.7, 'University of North Carolina': 0.6,
        'New York University': 0.6, 'Harvard': 0.7
      },
      // Business
      'Business': {
        'Harvard': 1.0, 'Stanford': 0.95, 'University of Michigan': 0.9, 'UC Berkeley': 0.85,
        'UT Austin': 0.85, 'University of North Carolina': 0.8, 'New York University': 0.8,
        'University of Washington': 0.7, 'University of Florida': 0.7,
        'MIT': 0.6, 'CMU': 0.6
      },
      // Arts
      'Art': {
        'New York University': 0.9, 'Harvard': 0.7, 'Stanford': 0.6, 'UC Berkeley': 0.7,
        'University of Michigan': 0.7, 'UT Austin': 0.6, 'University of Washington': 0.6,
        'University of Florida': 0.5, 'University of North Carolina': 0.6,
        'MIT': 0.3, 'CMU': 0.4
      },
      // Medicine
      'Medicine': {
        'Harvard': 1.0, 'Stanford': 0.95, 'University of Michigan': 0.9, 'UC Berkeley': 0.8,
        'University of North Carolina': 0.85, 'UT Austin': 0.8, 'University of Washington': 0.8,
        'University of Florida': 0.7, 'New York University': 0.75,
        'MIT': 0.6, 'CMU': 0.5
      }
    };

    // Default program weights for schools not in specific lists
    this.defaultProgramWeights = {
      'Computer Science': 0.7, 'Engineering': 0.75, 'Business': 0.8, 'Psychology': 0.7,
      'Biology': 0.75, 'Chemistry': 0.75, 'Physics': 0.8, 'Mathematics': 0.8,
      'English': 0.6, 'History': 0.6, 'Political Science': 0.65, 'Economics': 0.75,
      'Sociology': 0.65, 'Anthropology': 0.6, 'Art': 0.65, 'Music': 0.65,
      'Theater': 0.6, 'Film': 0.65, 'Journalism': 0.6, 'Communications': 0.6,
      'Education': 0.6, 'Nursing': 0.75, 'Architecture': 0.75, 'Design': 0.65,
      'Environmental Science': 0.75, 'Agriculture': 0.65, 'Veterinary': 0.8,
      'Pharmacy': 0.8, 'Dentistry': 0.8, 'Public Health': 0.7, 'Social Work': 0.6,
      'Criminal Justice': 0.6, 'Law': 0.8, 'Medicine': 0.85
    };

    // Financial aid probability based on school type and student profile
    this.financialAidFactors = {
      private: {
        highNeed: 0.8, mediumNeed: 0.6, lowNeed: 0.3
      },
      public: {
        highNeed: 0.6, mediumNeed: 0.4, lowNeed: 0.2
      }
    };

    // Cost of living adjustments by region
    this.costOfLivingMultipliers = {
      'New York': 1.8, 'California': 1.6, 'Massachusetts': 1.5,
      'Washington': 1.4, 'Michigan': 1.0, 'Texas': 0.9,
      'Florida': 0.95, 'North Carolina': 0.9
    };

    // Climate preferences with refined penalties
    this.climateZones = {
      warm: ['California', 'Florida', 'Texas'],
      moderate: ['North Carolina', 'Washington'],
      cold: ['Massachusetts', 'Michigan', 'New York']
    };

    // Transfer-friendly schools (good pathways to top programs)
    this.transferFriendlySchools = {
      'University of California': ['UC Berkeley', 'UCLA', 'UC San Diego'],
      'California State University': ['Cal Poly SLO', 'San Diego State', 'Cal State Long Beach'],
      'Community Colleges': ['Santa Monica College', 'De Anza College', 'Pasadena City College']
    };
  }

  // Calculate admission probability with refined overqualified penalties
  calculateAdmissionProbability(studentGPA, schoolAvgGPA, schoolAcceptanceRate) {
    if (!studentGPA || !schoolAvgGPA) return 0.5;

    const gpaRatio = studentGPA / schoolAvgGPA;
    let baseProbability = 0.5;

    // GPA-based probability curve
    if (gpaRatio >= 1.2) {
      baseProbability = 0.95; // Significantly above average
    } else if (gpaRatio >= 1.1) {
      baseProbability = 0.85; // Well above average
    } else if (gpaRatio >= 1.0) {
      baseProbability = 0.75; // Above average
    } else if (gpaRatio >= 0.9) {
      baseProbability = 0.6; // Competitive
    } else if (gpaRatio >= 0.8) {
      baseProbability = 0.4; // Below average
    } else if (gpaRatio >= 0.7) {
      baseProbability = 0.25; // Significantly below
    } else {
      baseProbability = 0.1; // Very low chance
    }

    // Refined overqualified penalties
    if (gpaRatio >= 1.3) {
      baseProbability *= 0.85; // 15% penalty for significant overqualification
    } else if (gpaRatio >= 1.1) {
      baseProbability *= 0.95; // 5% penalty for slight overqualification
    }

    // Factor in school's acceptance rate
    const acceptanceRateFactor = schoolAcceptanceRate / 100;
    const finalProbability = (baseProbability + acceptanceRateFactor) / 2;

    return Math.min(Math.max(finalProbability, 0.05), 0.95); // Clamp between 5% and 95%
  }

  // Calculate academic trajectory bonus
  calculateAcademicTrajectoryBonus(gradeTrend) {
    if (!gradeTrend) return 0;
    
    switch (gradeTrend) {
      case 'upward':
        return 3; // Upward trend bonus
      case 'consistent':
        return 2; // Consistent high performance
      case 'downward':
        return -2; // Downward trend penalty
      default:
        return 0;
    }
  }

  // Calculate academic score with major-specific weighting and trajectory bonus
  calculateAcademicScore(desiredMajor, school, studentGPA, schoolAvgGPA, gradeTrend) {
    let score = 0;
    
    // Get school-specific program strength
    const programStrength = this.schoolProgramStrength[desiredMajor]?.[school.name] || 
                           this.defaultProgramWeights[desiredMajor] || 0.7;
    
    // Program strength match (weighted by school-specific strength)
    if (desiredMajor && school.strongPrograms.includes(desiredMajor)) {
      score += 30 * programStrength; // Max 30 points for program strength
    }
    
    // GPA compatibility with admission probability
    const admissionProbability = this.calculateAdmissionProbability(
      studentGPA, schoolAvgGPA, school.acceptanceRate
    );
    
    // Convert admission probability to score (0-20 points)
    score += admissionProbability * 20;
    
    // Academic trajectory bonus
    score += this.calculateAcademicTrajectoryBonus(gradeTrend);
    
    return score;
  }

  // Calculate financial fit with net price consideration
  calculateFinancialScore(studentBudget, school, financialAid, studentState) {
    let score = 0;
    
    // Determine if in-state vs out-of-state
    const isInState = studentState && school.location.includes(studentState);
    const effectiveTuition = isInState ? school.tuition * 0.6 : school.tuition; // 40% discount for in-state
    
    // Add living costs based on region
    const region = this.getRegionFromLocation(school.location);
    const costOfLivingMultiplier = this.costOfLivingMultipliers[region] || 1.0;
    const totalCost = effectiveTuition + (15000 * costOfLivingMultiplier); // Base living cost
    
    // Direct cost comparison
    if (studentBudget && totalCost) {
      const costRatio = totalCost / studentBudget;
      
      if (costRatio <= 0.7) {
        score += 15; // Well within budget
      } else if (costRatio <= 0.9) {
        score += 12; // Within budget
      } else if (costRatio <= 1.1) {
        score += 8;  // Slightly over budget
      } else if (costRatio <= 1.3) {
        score += 4;  // Over budget
      } else {
        score -= 5;  // Significantly over budget (negative points)
      }
    }
    
    // Financial aid consideration
    if (financialAid === 'yes') {
      const schoolType = school.tuition > 45000 ? 'private' : 'public';
      const aidLikelihood = this.financialAidFactors[schoolType]?.mediumNeed || 0;
      score += aidLikelihood * 8; // Additional points for aid potential
    }
    
    // In-state bonus
    if (isInState) {
      score += 5; // Bonus for in-state tuition
    }
    
    return Math.max(score, -10); // Cap negative points at -10
  }

  // Calculate personality compatibility score
  calculatePersonalityScore(studentPersonality, schoolPersonality) {
    if (!studentPersonality || !schoolPersonality) return 0;
    
    const compatibility = this.personalityCompatibility[studentPersonality]?.[schoolPersonality] || 0;
    return compatibility * 15; // Max 15 points (reduced from 25)
  }

  // Calculate location and size preferences with refined climate penalties
  calculateLocationSizeScore(assessment, school) {
    let score = 0;
    
    // Location preference with distance and climate
    if (assessment.preferredLocation && school.location) {
      const locationMatch = this.enhancedLocationMatch(
        assessment.preferredLocation.toLowerCase(),
        school.location.toLowerCase()
      );
      score += locationMatch * 6; // Max 6 points for location
      
      // Refined climate preference with less punitive penalties
      if (assessment.climatePreference) {
        const climateMatch = this.climateMatch(assessment.climatePreference, school.location);
        if (climateMatch === 1.0) {
          score += 2; // Perfect climate match
        } else {
          // Check for very wrong climate (warm preference + very cold school)
          const isVeryWrongClimate = this.isVeryWrongClimate(assessment.climatePreference, school.location);
          if (isVeryWrongClimate) {
            score -= 2; // Penalty for very wrong climate
          } else {
            score -= 1; // Minor penalty for wrong climate
          }
        }
      }
    }
    
    // Size preference with tolerance
    if (assessment.preferredSize && school.studentPopulation) {
      const sizeRatio = school.studentPopulation / assessment.preferredSize;
      if (sizeRatio >= 0.7 && sizeRatio <= 1.3) {
        score += 2; // Within 30% tolerance
      } else if (sizeRatio >= 0.5 && sizeRatio <= 1.5) {
        score += 1; // Within 50% tolerance
      } else {
        score -= 2; // Penalty for poor size match
      }
    }
    
    return Math.max(score, -5); // Cap negative points at -5
  }

  // Check for very wrong climate combinations
  isVeryWrongClimate(preferredClimate, schoolLocation) {
    const region = this.getRegionFromLocation(schoolLocation);
    
    // Very wrong combinations
    if (preferredClimate === 'warm' && region === 'Massachusetts') return true;
    if (preferredClimate === 'warm' && region === 'Michigan') return true;
    if (preferredClimate === 'warm' && region === 'New York') return true;
    if (preferredClimate === 'cold' && region === 'California') return true;
    if (preferredClimate === 'cold' && region === 'Florida') return true;
    if (preferredClimate === 'cold' && region === 'Texas') return true;
    
    return false;
  }

  // Enhanced location matching with distance and climate
  enhancedLocationMatch(preferred, actual) {
    if (actual.includes(preferred) || preferred.includes(actual)) {
      return 1.0; // Exact or substring match
    }
    
    // State matching with major cities
    const states = {
      'california': ['stanford', 'berkeley', 'ucla', 'usc', 'san francisco', 'los angeles'],
      'massachusetts': ['harvard', 'mit', 'boston', 'cambridge'],
      'new york': ['nyu', 'columbia', 'cornell', 'new york', 'manhattan'],
      'texas': ['austin', 'dallas', 'houston', 'san antonio'],
      'florida': ['gainesville', 'miami', 'orlando', 'tampa'],
      'washington': ['seattle', 'spokane', 'tacoma'],
      'north carolina': ['chapel hill', 'durham', 'raleigh', 'charlotte'],
      'michigan': ['ann arbor', 'detroit', 'lansing']
    };
    
    for (const [state, cities] of Object.entries(states)) {
      if ((preferred.includes(state) || cities.some(city => preferred.includes(city))) &&
          (actual.includes(state) || cities.some(city => actual.includes(city)))) {
        return 0.8; // State-level match
      }
    }
    
    return 0; // No match
  }

  // Climate matching
  climateMatch(preferredClimate, schoolLocation) {
    const region = this.getRegionFromLocation(schoolLocation);
    
    for (const [climate, regions] of Object.entries(this.climateZones)) {
      if (climate === preferredClimate && regions.includes(region)) {
        return 1.0;
      }
    }
    
    return 0;
  }

  // Get region from location
  getRegionFromLocation(location) {
    if (location.includes('California')) return 'California';
    if (location.includes('Massachusetts')) return 'Massachusetts';
    if (location.includes('New York')) return 'New York';
    if (location.includes('Texas')) return 'Texas';
    if (location.includes('Florida')) return 'Florida';
    if (location.includes('Washington')) return 'Washington';
    if (location.includes('North Carolina')) return 'North Carolina';
    if (location.includes('Michigan')) return 'Michigan';
    return 'Other';
  }

  // Check if school is transfer-friendly
  isTransferFriendly(schoolName) {
    for (const [category, schools] of Object.entries(this.transferFriendlySchools)) {
      if (schools.some(school => schoolName.includes(school))) {
        return true;
      }
    }
    return false;
  }

  // Simplified extracurricular alignment
  calculateExtracurricularScore(activities, schoolPrograms) {
    if (!activities || activities.length === 0) return 0;
    
    let score = 0;
    const activityCategories = this.categorizeActivities(activities);
    
    // STEM activities → STEM programs
    if (activityCategories.stem && this.hasSTEMPrograms(schoolPrograms)) {
      score += 3;
    }
    
    // Arts activities → Arts programs
    if (activityCategories.arts && this.hasArtsPrograms(schoolPrograms)) {
      score += 3;
    }
    
    // Sports activities → Athletic programs
    if (activityCategories.sports) {
      score += 2;
    }
    
    // Leadership activities → Business/political programs
    if (activityCategories.leadership && this.hasLeadershipPrograms(schoolPrograms)) {
      score += 2;
    }
    
    return Math.min(score, 5); // Cap at 5 points
  }

  // Categorize activities into buckets
  categorizeActivities(activities) {
    const categories = { stem: false, arts: false, sports: false, leadership: false };
    
    const stemKeywords = ['coding', 'computer', 'math', 'science', 'engineering', 'robotics', 'chemistry', 'physics'];
    const artsKeywords = ['art', 'music', 'theater', 'drama', 'dance', 'creative', 'design', 'film'];
    const sportsKeywords = ['soccer', 'basketball', 'football', 'tennis', 'swimming', 'track', 'volleyball', 'baseball'];
    const leadershipKeywords = ['president', 'captain', 'leader', 'officer', 'chair', 'coordinator', 'director'];
    
    for (const activity of activities) {
      const activityText = activity.name.toLowerCase();
      
      if (stemKeywords.some(keyword => activityText.includes(keyword))) {
        categories.stem = true;
      }
      if (artsKeywords.some(keyword => activityText.includes(keyword))) {
        categories.arts = true;
      }
      if (sportsKeywords.some(keyword => activityText.includes(keyword))) {
        categories.sports = true;
      }
      if (leadershipKeywords.some(keyword => activityText.includes(keyword))) {
        categories.leadership = true;
      }
    }
    
    return categories;
  }

  // Check for STEM programs
  hasSTEMPrograms(programs) {
    const stemPrograms = ['Computer Science', 'Engineering', 'Physics', 'Chemistry', 'Mathematics', 'Biology'];
    return programs.some(program => stemPrograms.includes(program));
  }

  // Check for Arts programs
  hasArtsPrograms(programs) {
    const artsPrograms = ['Art', 'Music', 'Theater', 'Film', 'Design', 'Dance'];
    return programs.some(program => artsPrograms.includes(program));
  }

  // Check for Leadership programs
  hasLeadershipPrograms(programs) {
    const leadershipPrograms = ['Business', 'Political Science', 'Economics', 'Public Policy'];
    return programs.some(program => leadershipPrograms.includes(program));
  }

  // Determine safety/target/reach classification
  getAdmissionCategory(admissionProbability) {
    if (admissionProbability >= 0.8) return 'Safety';
    if (admissionProbability >= 0.4) return 'Target';
    return 'Reach';
  }

  // Adaptive safety/target/reach balance based on student GPA
  getAdaptiveBalance(studentGPA) {
    if (studentGPA >= 3.7) {
      return { safety: 1, target: 4, reach: 3 }; // High-achieving students
    } else if (studentGPA >= 3.0) {
      return { safety: 3, target: 4, reach: 1 }; // Average students
    } else {
      return { safety: 4, target: 3, reach: 1 }; // Struggling students
    }
  }

  // Calculate confidence level for match
  calculateConfidenceLevel(assessment, school) {
    let confidence = 0;
    let totalFactors = 0;
    
    // Check data completeness
    if (assessment.currentGPA) { confidence += 1; totalFactors += 1; }
    if (assessment.desiredMajor) { confidence += 1; totalFactors += 1; }
    if (assessment.maxBudget) { confidence += 1; totalFactors += 1; }
    if (assessment.personalityType) { confidence += 1; totalFactors += 1; }
    if (assessment.preferredLocation) { confidence += 1; totalFactors += 1; }
    if (assessment.activities && assessment.activities.length > 0) { confidence += 1; totalFactors += 1; }
    
    // Check school data quality
    if (school.averageGPA) { confidence += 1; totalFactors += 1; }
    if (school.acceptanceRate) { confidence += 1; totalFactors += 1; }
    if (school.strongPrograms && school.strongPrograms.length > 0) { confidence += 1; totalFactors += 1; }
    
    const confidenceRatio = confidence / totalFactors;
    
    if (confidenceRatio >= 0.8) return 'High';
    if (confidenceRatio >= 0.6) return 'Medium';
    return 'Low';
  }

  // Main matching function with enhanced scoring and adaptive balancing
  calculateMatches(assessment, schools) {
    const matches = schools.map(school => {
      let totalScore = 0;
      let breakdown = {};
      
      // Academic match (50 points max)
      const academicScore = this.calculateAcademicScore(
        assessment.desiredMajor,
        school,
        assessment.currentGPA,
        school.averageGPA,
        assessment.gradeTrend
      );
      totalScore += academicScore;
      breakdown.academic = academicScore;
      
      // Financial fit (20 points max)
      const financialScore = this.calculateFinancialScore(
        assessment.maxBudget,
        school,
        assessment.financialAid,
        assessment.homeState
      );
      totalScore += financialScore;
      breakdown.financial = financialScore;
      
      // Personality compatibility (15 points max)
      const personalityScore = this.calculatePersonalityScore(
        assessment.personalityType, 
        school.personalityMatch
      );
      totalScore += personalityScore;
      breakdown.personality = personalityScore;
      
      // Location and size preferences (10 points max)
      const locationSizeScore = this.calculateLocationSizeScore(assessment, school);
      totalScore += locationSizeScore;
      breakdown.locationSize = locationSizeScore;
      
      // Extracurricular alignment (5 points max)
      const extracurricularScore = this.calculateExtracurricularScore(
        assessment.activities,
        school.strongPrograms
      );
      totalScore += extracurricularScore;
      breakdown.extracurricular = extracurricularScore;
      
      // Calculate admission probability for categorization
      const admissionProbability = this.calculateAdmissionProbability(
        assessment.currentGPA,
        school.averageGPA,
        school.acceptanceRate
      );
      
      // Apply minimum thresholds
      if (assessment.currentGPA < school.averageGPA * 0.8) {
        totalScore = Math.min(totalScore, 30); // Cap at 30 if significantly below average
      }
      
      if (assessment.maxBudget && school.tuition > assessment.maxBudget * 1.5) {
        totalScore = Math.min(totalScore, 20); // Cap at 20 if unaffordable
      }
      
      // Normalize score to 0-100 range
      totalScore = Math.min(Math.max(totalScore, 0), 100);
      
      // Calculate confidence level
      const confidenceLevel = this.calculateConfidenceLevel(assessment, school);
      
      return {
        ...school,
        matchScore: Math.round(totalScore),
        scoreBreakdown: breakdown,
        matchLevel: this.getMatchLevel(totalScore),
        admissionProbability: admissionProbability,
        admissionCategory: this.getAdmissionCategory(admissionProbability),
        confidenceLevel: confidenceLevel,
        isTransferFriendly: this.isTransferFriendly(school.name),
        explanation: this.getMatchExplanation(assessment, school, breakdown),
        topReasons: this.getTopReasons(assessment, school, breakdown)
      };
    }).sort((a, b) => b.matchScore - a.matchScore);
    
    // Ensure balanced recommendations with adaptive distribution
    return this.balanceRecommendationsAdaptive(matches, assessment.currentGPA);
  }

  // Adaptive balancing based on student GPA
  balanceRecommendationsAdaptive(matches, studentGPA) {
    const balance = this.getAdaptiveBalance(studentGPA);
    const categorized = {
      Safety: matches.filter(m => m.admissionCategory === 'Safety'),
      Target: matches.filter(m => m.admissionCategory === 'Target'),
      Reach: matches.filter(m => m.admissionCategory === 'Reach')
    };
    
    const balanced = [];
    
    // Add safety schools based on adaptive distribution
    balanced.push(...categorized.Safety.slice(0, balance.safety));
    
    // Add target schools based on adaptive distribution
    balanced.push(...categorized.Target.slice(0, balance.target));
    
    // Add reach schools based on adaptive distribution
    balanced.push(...categorized.Reach.slice(0, balance.reach));
    
    // Fill remaining slots with best overall matches
    const remaining = matches.filter(m => !balanced.includes(m));
    balanced.push(...remaining.slice(0, 2));
    
    return balanced.slice(0, 10); // Return top 10
  }

  // Get match level description
  getMatchLevel(score) {
    if (score >= 85) return 'Perfect Match';
    if (score >= 70) return 'Excellent Match';
    if (score >= 55) return 'Good Match';
    if (score >= 40) return 'Fair Match';
    return 'Poor Match';
  }

  // Get detailed explanation for a match
  getMatchExplanation(assessment, school, scoreBreakdown) {
    const explanations = [];
    
    if (scoreBreakdown.academic > 25) {
      explanations.push(`Excellent academic fit for ${assessment.desiredMajor} program`);
    } else if (scoreBreakdown.academic > 15) {
      explanations.push(`Good academic fit for ${assessment.desiredMajor} program`);
    }
    
    if (scoreBreakdown.financial > 10) {
      explanations.push('Good financial fit within your budget');
    }
    
    if (scoreBreakdown.personality > 10) {
      explanations.push(`Strong personality compatibility with ${school.personalityMatch} environment`);
    }
    
    if (scoreBreakdown.locationSize > 5) {
      explanations.push('Matches your location and size preferences');
    }
    
    if (scoreBreakdown.extracurricular > 2) {
      explanations.push('Your activities align well with school programs');
    }
    
    return explanations;
  }

  // Get top 2-3 reasons for the match
  getTopReasons(assessment, school, scoreBreakdown) {
    const reasons = [];
    
    // Academic reasons
    if (scoreBreakdown.academic > 20) {
      const programStrength = this.schoolProgramStrength[assessment.desiredMajor]?.[school.name] || 0.7;
      if (programStrength >= 0.9) {
        reasons.push(`Top-ranked ${assessment.desiredMajor} program`);
      } else if (programStrength >= 0.8) {
        reasons.push(`Strong ${assessment.desiredMajor} program`);
      } else {
        reasons.push(`Good ${assessment.desiredMajor} program`);
      }
    }
    
    // Financial reasons
    if (scoreBreakdown.financial > 12) {
      reasons.push('Excellent financial fit');
    } else if (scoreBreakdown.financial > 8) {
      reasons.push('Good financial fit');
    }
    
    // Location reasons
    if (scoreBreakdown.locationSize > 4) {
      reasons.push('Matches your location preferences');
    }
    
    // Personality reasons
    if (scoreBreakdown.personality > 10) {
      reasons.push(`Great ${school.personalityMatch} environment match`);
    }
    
    // Transfer-friendly bonus
    if (this.isTransferFriendly(school.name)) {
      reasons.push('Transfer-friendly with good pathways');
    }
    
    return reasons.slice(0, 3); // Return top 3 reasons
  }
}

module.exports = CollegeMatchingAlgorithm; 