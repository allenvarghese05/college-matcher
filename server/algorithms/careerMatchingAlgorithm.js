// Career Matching Algorithm
// Integrates with college matching system to provide career pathway alignment

const careers = require('../data/careers');

class CareerMatchingAlgorithm {
  constructor() {
    this.careers = careers;
    this.scoringWeights = {
      skills: 30,
      interests: 25,
      values: 20,
      work_style: 15,
      education: 10
    };
  }

  // Calculate career match score
  calculateCareerMatch(assessmentData, career) {
    let totalScore = 0;
    let breakdown = {};

    // Skills match (30 points)
    const skillsScore = this.calculateSkillsMatch(assessmentData, career);
    totalScore += skillsScore;
    breakdown.skills = skillsScore;

    // Interests match (25 points)
    const interestsScore = this.calculateInterestsMatch(assessmentData, career);
    totalScore += interestsScore;
    breakdown.interests = interestsScore;

    // Values match (20 points)
    const valuesScore = this.calculateValuesMatch(assessmentData, career);
    totalScore += valuesScore;
    breakdown.values = valuesScore;

    // Work style match (15 points)
    const workStyleScore = this.calculateWorkStyleMatch(assessmentData, career);
    totalScore += workStyleScore;
    breakdown.workStyle = workStyleScore;

    // Education match (10 points)
    const educationScore = this.calculateEducationMatch(assessmentData, career);
    totalScore += educationScore;
    breakdown.education = educationScore;

    return {
      career: career,
      matchScore: Math.round(totalScore),
      scoreBreakdown: breakdown,
      matchLevel: this.getMatchLevel(totalScore),
      explanation: this.getCareerMatchExplanation(assessmentData, career, breakdown),
      skillsGap: this.analyzeSkillsGap(assessmentData, career),
      educationalPathway: this.getEducationalPathway(career)
    };
  }

  // Calculate skills match
  calculateSkillsMatch(assessmentData, career) {
    let score = 0;
    const requiredSkills = career.skills || [];
    const studentSkills = this.extractSkillsFromAssessment(assessmentData);
    
    for (const skill of requiredSkills) {
      if (studentSkills.includes(skill)) {
        score += 6; // 6 points per matching skill (max 30 points for 5 skills)
      }
    }
    
    return Math.min(score, 30);
  }

  // Calculate interests match
  calculateInterestsMatch(assessmentData, career) {
    let score = 0;
    const careerInterests = career.interests || [];
    const studentInterests = this.extractInterestsFromAssessment(assessmentData);
    
    for (const interest of careerInterests) {
      if (studentInterests.includes(interest)) {
        score += 5; // 5 points per matching interest (max 25 points for 5 interests)
      }
    }
    
    return Math.min(score, 25);
  }

  // Calculate values match
  calculateValuesMatch(assessmentData, career) {
    let score = 0;
    const careerValues = career.values_alignment || [];
    const studentValues = this.extractValuesFromAssessment(assessmentData);
    
    for (const value of careerValues) {
      if (studentValues.includes(value)) {
        score += 4; // 4 points per matching value (max 20 points for 5 values)
      }
    }
    
    return Math.min(score, 20);
  }

  // Calculate work style match
  calculateWorkStyleMatch(assessmentData, career) {
    let score = 0;
    const careerWorkStyle = career.work_style || [];
    const studentWorkStyle = this.extractWorkStyleFromAssessment(assessmentData);
    
    for (const style of careerWorkStyle) {
      if (studentWorkStyle.includes(style)) {
        score += 7.5; // 7.5 points per matching work style (max 15 points for 2 styles)
      }
    }
    
    return Math.min(score, 15);
  }

  // Calculate education match
  calculateEducationMatch(assessmentData, career) {
    let score = 0;
    const studentEducationGoal = this.extractEducationGoalFromAssessment(assessmentData);
    const careerEducationRequired = career.education_required;
    
    if (careerEducationRequired === 'varies') {
      score = 5; // Neutral score for flexible education requirements
    } else if (studentEducationGoal === careerEducationRequired) {
      score = 10; // Perfect match
    } else if (this.isEducationCompatible(studentEducationGoal, careerEducationRequired)) {
      score = 7; // Compatible education levels
    } else {
      score = 3; // Somewhat compatible
    }
    
    return score;
  }

  // Extract skills from assessment data
  extractSkillsFromAssessment(assessmentData) {
    const skills = [];
    
    // Map assessment responses to skills
    if (assessmentData.strongest_subjects?.includes('math')) skills.push('mathematics');
    if (assessmentData.strongest_subjects?.includes('science')) skills.push('research');
    if (assessmentData.strongest_subjects?.includes('english')) skills.push('writing');
    if (assessmentData.strongest_subjects?.includes('computer_science')) skills.push('programming');
    
    // Work style preferences
    if (assessmentData.team_individual === 'team') skills.push('teamwork');
    if (assessmentData.leadership_comfort === 'natural_leader') skills.push('leadership');
    if (assessmentData.attention_to_detail === 'high') skills.push('attention_to_detail');
    if (assessmentData.problem_solving === 'methodical') skills.push('analytical_thinking');
    
    return skills;
  }

  // Extract interests from assessment data
  extractInterestsFromAssessment(assessmentData) {
    const interests = [];
    
    // Career interests
    if (assessmentData.career_interest) interests.push(assessmentData.career_interest);
    
    // Academic interests
    if (assessmentData.strongest_subjects?.includes('science')) interests.push('science');
    if (assessmentData.strongest_subjects?.includes('computer_science')) interests.push('technology');
    if (assessmentData.strongest_subjects?.includes('arts')) interests.push('art');
    if (assessmentData.strongest_subjects?.includes('business')) interests.push('business');
    
    // Work preferences
    if (assessmentData.helping_orientation === 'direct_service') interests.push('helping_others');
    if (assessmentData.physical_mental === 'creative') interests.push('creativity');
    
    return interests;
  }

  // Extract values from assessment data
  extractValuesFromAssessment(assessmentData) {
    const values = [];
    
    // Financial priorities
    if (assessmentData.financial_priorities === 'high_income') values.push('high_salary');
    if (assessmentData.financial_priorities === 'comfortable') values.push('job_security');
    
    // Work-life balance
    if (assessmentData.work_life_balance === 'balanced') values.push('work_life_balance');
    
    // Social impact
    if (assessmentData.impact_on_others === 'help_individuals') values.push('helping_others');
    if (assessmentData.impact_on_others === 'serve_community') values.push('social_impact');
    
    // Recognition
    if (assessmentData.recognition_importance === 'public_recognition') values.push('recognition');
    
    // Intellectual stimulation
    if (assessmentData.intellectual_stimulation === 'constant_learning') values.push('intellectual_challenge');
    
    return values;
  }

  // Extract work style from assessment data
  extractWorkStyleFromAssessment(assessmentData) {
    const workStyles = [];
    
    if (assessmentData.team_individual === 'team') workStyles.push('team');
    if (assessmentData.team_individual === 'individual') workStyles.push('individual');
    if (assessmentData.team_individual === 'mixed') {
      workStyles.push('team');
      workStyles.push('individual');
    }
    
    return workStyles;
  }

  // Extract education goal from assessment data
  extractEducationGoalFromAssessment(assessmentData) {
    return assessmentData.educational_goals || 'bachelors';
  }

  // Check if education levels are compatible
  isEducationCompatible(studentGoal, careerRequired) {
    const educationLevels = {
      'associates': 1,
      'bachelors': 2,
      'masters': 3,
      'doctorate': 4,
      'professional': 4
    };
    
    const studentLevel = educationLevels[studentGoal] || 2;
    const careerLevel = educationLevels[careerRequired] || 2;
    
    return studentLevel >= careerLevel;
  }

  // Get match level description
  getMatchLevel(score) {
    if (score >= 85) return 'Perfect Match';
    if (score >= 70) return 'Excellent Match';
    if (score >= 55) return 'Good Match';
    if (score >= 40) return 'Fair Match';
    return 'Poor Match';
  }

  // Get career match explanation
  getCareerMatchExplanation(assessmentData, career, breakdown) {
    const explanations = [];
    
    if (breakdown.skills > 15) {
      explanations.push(`Strong skills alignment with ${career.title} requirements`);
    }
    
    if (breakdown.interests > 12) {
      explanations.push(`Your interests align well with ${career.category} field`);
    }
    
    if (breakdown.values > 10) {
      explanations.push(`Your values match the ${career.title} profession`);
    }
    
    if (breakdown.workStyle > 7) {
      explanations.push(`Your work style preferences fit this career well`);
    }
    
    return explanations;
  }

  // Analyze skills gap
  analyzeSkillsGap(assessmentData, career) {
    const studentSkills = this.extractSkillsFromAssessment(assessmentData);
    const requiredSkills = career.skills || [];
    const missingSkills = requiredSkills.filter(skill => !studentSkills.includes(skill));
    
    return {
      missingSkills: missingSkills,
      developmentAreas: career.skills_gap_analysis?.technical || [],
      softSkillsNeeded: career.skills_gap_analysis?.soft_skills || []
    };
  }

  // Get educational pathway
  getEducationalPathway(career) {
    return {
      recommendedMajors: career.typical_majors || [],
      educationLevel: career.education_required,
      certifications: career.certifications || [],
      timeline: this.getEducationTimeline(career.education_required)
    };
  }

  // Get education timeline
  getEducationTimeline(educationRequired) {
    switch (educationRequired) {
      case 'associates':
        return '2 years';
      case 'bachelors':
        return '4 years';
      case 'masters':
        return '6 years (4 + 2)';
      case 'doctorate':
        return '8-10 years (4 + 2-4 + 2-4)';
      case 'professional':
        return '7-8 years (4 + 3-4)';
      default:
        return 'Varies';
    }
  }

  // Generate career recommendations
  generateCareerRecommendations(assessmentData) {
    const matches = this.careers.map(career => 
      this.calculateCareerMatch(assessmentData, career)
    );
    
    // Sort by match score
    matches.sort((a, b) => b.matchScore - a.matchScore);
    
    // Return top 10 matches
    return matches.slice(0, 10);
  }

  // Integrate career recommendations with college matching
  integrateWithCollegeMatching(careerRecommendations, collegeMatches) {
    return collegeMatches.map(college => {
      // Find best matching career for this college
      const bestCareerMatch = careerRecommendations.find(career => 
        career.career.typical_majors.some(major => 
          college.strongPrograms.includes(major)
        )
      );
      
      let careerPathwayScore = 0;
      let careerAlignment = null;
      
      if (bestCareerMatch) {
        careerPathwayScore = Math.round(bestCareerMatch.matchScore * 0.1); // 10 points max
        careerAlignment = {
          career: bestCareerMatch.career.title,
          matchScore: bestCareerMatch.matchScore,
          explanation: `Strong alignment with ${bestCareerMatch.career.title} career path`
        };
      }
      
      return {
        ...college,
        careerPathwayScore: careerPathwayScore,
        careerAlignment: careerAlignment,
        totalScore: college.matchScore + careerPathwayScore
      };
    }).sort((a, b) => b.totalScore - a.totalScore);
  }
}

module.exports = CareerMatchingAlgorithm; 