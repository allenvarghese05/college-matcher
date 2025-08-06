// Comprehensive Career Database
// 200+ career profiles with detailed information for career matching

const careers = [
  {
    id: 'software_engineer',
    title: 'Software Engineer',
    category: 'Technology',
    description: 'Design, develop, and maintain software applications and systems',
    skills: ['programming', 'problem_solving', 'analytical_thinking', 'mathematics', 'attention_to_detail'],
    interests: ['technology', 'building', 'problem_solving', 'innovation'],
    work_environment: ['office', 'remote'],
    education_required: 'bachelors',
    typical_majors: ['Computer Science', 'Software Engineering', 'Information Technology'],
    salary_range: { min: 70000, max: 150000 },
    growth_outlook: 'Excellent',
    work_style: ['individual', 'team'],
    personality_traits: ['analytical', 'logical', 'detail_oriented'],
    values_alignment: ['intellectual_challenge', 'creativity', 'high_salary'],
    skills_gap_analysis: {
      technical: ['Programming languages', 'Software development methodologies', 'Database management'],
      soft_skills: ['Communication', 'Teamwork', 'Time management']
    }
  },
  {
    id: 'data_scientist',
    title: 'Data Scientist',
    category: 'Technology',
    description: 'Analyze complex data to help organizations make informed decisions',
    skills: ['mathematics', 'statistics', 'programming', 'analytical_thinking', 'research'],
    interests: ['data_analysis', 'research', 'mathematics', 'technology'],
    work_environment: ['office', 'lab'],
    education_required: 'masters',
    typical_majors: ['Data Science', 'Statistics', 'Computer Science', 'Mathematics'],
    salary_range: { min: 80000, max: 160000 },
    growth_outlook: 'Excellent',
    work_style: ['individual', 'team'],
    personality_traits: ['analytical', 'curious', 'detail_oriented'],
    values_alignment: ['intellectual_challenge', 'high_salary', 'innovation'],
    skills_gap_analysis: {
      technical: ['Statistical analysis', 'Machine learning', 'Data visualization', 'Programming'],
      soft_skills: ['Communication', 'Business acumen', 'Problem solving']
    }
  },
  {
    id: 'physician',
    title: 'Physician',
    category: 'Healthcare',
    description: 'Diagnose and treat patients\' illnesses and injuries',
    skills: ['medical_knowledge', 'diagnostic_thinking', 'communication', 'empathy', 'attention_to_detail'],
    interests: ['healthcare', 'helping_others', 'science', 'problem_solving'],
    work_environment: ['hospital', 'office', 'clinic'],
    education_required: 'doctorate',
    typical_majors: ['Biology', 'Chemistry', 'Pre-Medicine'],
    salary_range: { min: 150000, max: 300000 },
    growth_outlook: 'Excellent',
    work_style: ['individual', 'team'],
    personality_traits: ['empathetic', 'analytical', 'responsible'],
    values_alignment: ['helping_others', 'high_salary', 'prestige', 'intellectual_challenge'],
    skills_gap_analysis: {
      technical: ['Medical knowledge', 'Diagnostic skills', 'Patient care'],
      soft_skills: ['Communication', 'Empathy', 'Leadership', 'Stress management']
    }
  },
  {
    id: 'nurse',
    title: 'Registered Nurse',
    category: 'Healthcare',
    description: 'Provide patient care and support in various healthcare settings',
    skills: ['patient_care', 'communication', 'empathy', 'attention_to_detail', 'teamwork'],
    interests: ['healthcare', 'helping_others', 'science'],
    work_environment: ['hospital', 'clinic', 'nursing_home'],
    education_required: 'bachelors',
    typical_majors: ['Nursing', 'Health Sciences'],
    salary_range: { min: 50000, max: 100000 },
    growth_outlook: 'Excellent',
    work_style: ['team'],
    personality_traits: ['empathetic', 'caring', 'responsible'],
    values_alignment: ['helping_others', 'job_security', 'social_impact'],
    skills_gap_analysis: {
      technical: ['Patient care', 'Medical procedures', 'Health assessment'],
      soft_skills: ['Communication', 'Empathy', 'Teamwork', 'Stress management']
    }
  },
  {
    id: 'teacher',
    title: 'Teacher',
    category: 'Education',
    description: 'Educate students in various subjects and grade levels',
    skills: ['communication', 'patience', 'organization', 'creativity', 'leadership'],
    interests: ['teaching', 'helping_others', 'education'],
    work_environment: ['classroom', 'school'],
    education_required: 'bachelors',
    typical_majors: ['Education', 'Subject-specific majors'],
    salary_range: { min: 40000, max: 80000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['patient', 'empathetic', 'organized'],
    values_alignment: ['helping_others', 'social_impact', 'work_life_balance'],
    skills_gap_analysis: {
      technical: ['Subject knowledge', 'Teaching methods', 'Classroom management'],
      soft_skills: ['Communication', 'Patience', 'Leadership', 'Creativity']
    }
  },
  {
    id: 'financial_analyst',
    title: 'Financial Analyst',
    category: 'Business',
    description: 'Analyze financial data to help businesses make investment decisions',
    skills: ['mathematics', 'analytical_thinking', 'attention_to_detail', 'research', 'communication'],
    interests: ['finance', 'business', 'data_analysis', 'mathematics'],
    work_environment: ['office'],
    education_required: 'bachelors',
    typical_majors: ['Finance', 'Economics', 'Business', 'Accounting'],
    salary_range: { min: 60000, max: 120000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['analytical', 'detail_oriented', 'organized'],
    values_alignment: ['high_salary', 'intellectual_challenge', 'job_security'],
    skills_gap_analysis: {
      technical: ['Financial analysis', 'Excel', 'Financial modeling', 'Accounting'],
      soft_skills: ['Communication', 'Presentation skills', 'Business acumen']
    }
  },
  {
    id: 'marketing_manager',
    title: 'Marketing Manager',
    category: 'Business',
    description: 'Develop and execute marketing strategies to promote products or services',
    skills: ['communication', 'creativity', 'leadership', 'analytical_thinking', 'organization'],
    interests: ['marketing', 'business', 'creativity', 'communication'],
    work_environment: ['office'],
    education_required: 'bachelors',
    typical_majors: ['Marketing', 'Business', 'Communications'],
    salary_range: { min: 60000, max: 130000 },
    growth_outlook: 'Good',
    work_style: ['team', 'individual'],
    personality_traits: ['creative', 'outgoing', 'organized'],
    values_alignment: ['creativity', 'recognition', 'high_salary'],
    skills_gap_analysis: {
      technical: ['Marketing strategies', 'Digital marketing', 'Analytics', 'Brand management'],
      soft_skills: ['Leadership', 'Communication', 'Creativity', 'Strategic thinking']
    }
  },
  {
    id: 'psychologist',
    title: 'Psychologist',
    category: 'Healthcare',
    description: 'Study human behavior and mental processes, provide therapy and counseling',
    skills: ['empathy', 'communication', 'analytical_thinking', 'research', 'patience'],
    interests: ['psychology', 'helping_others', 'research', 'human_behavior'],
    work_environment: ['office', 'clinic', 'hospital'],
    education_required: 'doctorate',
    typical_majors: ['Psychology', 'Counseling'],
    salary_range: { min: 60000, max: 120000 },
    growth_outlook: 'Good',
    work_style: ['individual'],
    personality_traits: ['empathetic', 'patient', 'analytical'],
    values_alignment: ['helping_others', 'intellectual_challenge', 'social_impact'],
    skills_gap_analysis: {
      technical: ['Psychological assessment', 'Therapy techniques', 'Research methods'],
      soft_skills: ['Empathy', 'Active listening', 'Communication', 'Patience']
    }
  },
  {
    id: 'engineer',
    title: 'Engineer',
    category: 'Engineering',
    description: 'Design and build systems, structures, and products using scientific principles',
    skills: ['mathematics', 'problem_solving', 'analytical_thinking', 'attention_to_detail', 'creativity'],
    interests: ['engineering', 'building', 'problem_solving', 'science'],
    work_environment: ['office', 'lab', 'field'],
    education_required: 'bachelors',
    typical_majors: ['Engineering', 'Physics', 'Mathematics'],
    salary_range: { min: 70000, max: 140000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['analytical', 'logical', 'detail_oriented'],
    values_alignment: ['intellectual_challenge', 'creativity', 'high_salary'],
    skills_gap_analysis: {
      technical: ['Engineering principles', 'CAD software', 'Technical analysis', 'Project management'],
      soft_skills: ['Communication', 'Teamwork', 'Problem solving', 'Leadership']
    }
  },
  {
    id: 'lawyer',
    title: 'Lawyer',
    category: 'Legal',
    description: 'Provide legal advice and representation to clients',
    skills: ['communication', 'analytical_thinking', 'research', 'persuasion', 'attention_to_detail'],
    interests: ['law', 'justice', 'communication', 'research'],
    work_environment: ['office', 'courtroom'],
    education_required: 'doctorate',
    typical_majors: ['Political Science', 'History', 'English', 'Pre-Law'],
    salary_range: { min: 80000, max: 200000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['analytical', 'persuasive', 'detail_oriented'],
    values_alignment: ['high_salary', 'prestige', 'intellectual_challenge'],
    skills_gap_analysis: {
      technical: ['Legal research', 'Case analysis', 'Legal writing', 'Court procedures'],
      soft_skills: ['Communication', 'Persuasion', 'Critical thinking', 'Negotiation']
    }
  },
  {
    id: 'artist',
    title: 'Artist',
    category: 'Arts',
    description: 'Create visual artwork using various mediums and techniques',
    skills: ['creativity', 'artistic_ability', 'attention_to_detail', 'visual_interpretation'],
    interests: ['art', 'creativity', 'visual_arts'],
    work_environment: ['studio', 'home', 'gallery'],
    education_required: 'bachelors',
    typical_majors: ['Fine Arts', 'Art History', 'Design'],
    salary_range: { min: 30000, max: 80000 },
    growth_outlook: 'Moderate',
    work_style: ['individual'],
    personality_traits: ['creative', 'expressive', 'independent'],
    values_alignment: ['creativity', 'autonomy', 'self_expression'],
    skills_gap_analysis: {
      technical: ['Artistic techniques', 'Digital tools', 'Portfolio development'],
      soft_skills: ['Creativity', 'Self-motivation', 'Marketing', 'Business skills']
    }
  },
  {
    id: 'social_worker',
    title: 'Social Worker',
    category: 'Social Services',
    description: 'Help people solve and cope with problems in their lives',
    skills: ['empathy', 'communication', 'organization', 'problem_solving', 'patience'],
    interests: ['helping_others', 'social_work', 'community_service'],
    work_environment: ['office', 'field', 'hospital'],
    education_required: 'bachelors',
    typical_majors: ['Social Work', 'Psychology', 'Sociology'],
    salary_range: { min: 40000, max: 70000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['empathetic', 'caring', 'patient'],
    values_alignment: ['helping_others', 'social_impact', 'meaningful_causes'],
    skills_gap_analysis: {
      technical: ['Case management', 'Social work methods', 'Community resources'],
      soft_skills: ['Empathy', 'Communication', 'Problem solving', 'Cultural sensitivity']
    }
  },
  {
    id: 'scientist',
    title: 'Research Scientist',
    category: 'Science',
    description: 'Conduct research to advance knowledge in various scientific fields',
    skills: ['research', 'analytical_thinking', 'attention_to_detail', 'mathematics', 'creativity'],
    interests: ['science', 'research', 'discovery', 'problem_solving'],
    work_environment: ['lab', 'field', 'office'],
    education_required: 'doctorate',
    typical_majors: ['Biology', 'Chemistry', 'Physics', 'Mathematics'],
    salary_range: { min: 70000, max: 150000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['curious', 'analytical', 'patient'],
    values_alignment: ['intellectual_challenge', 'discovery', 'innovation'],
    skills_gap_analysis: {
      technical: ['Research methods', 'Laboratory techniques', 'Data analysis', 'Scientific writing'],
      soft_skills: ['Critical thinking', 'Communication', 'Collaboration', 'Problem solving']
    }
  },
  {
    id: 'entrepreneur',
    title: 'Entrepreneur',
    category: 'Business',
    description: 'Start and run your own business venture',
    skills: ['leadership', 'risk_taking', 'creativity', 'organization', 'communication'],
    interests: ['business', 'entrepreneurship', 'innovation', 'leadership'],
    work_environment: ['office', 'home', 'various'],
    education_required: 'varies',
    typical_majors: ['Business', 'Entrepreneurship', 'Any field'],
    salary_range: { min: 0, max: 1000000 },
    growth_outlook: 'Variable',
    work_style: ['individual', 'team'],
    personality_traits: ['risk_taker', 'innovative', 'determined'],
    values_alignment: ['autonomy', 'creativity', 'high_potential_income'],
    skills_gap_analysis: {
      technical: ['Business planning', 'Financial management', 'Marketing', 'Operations'],
      soft_skills: ['Leadership', 'Risk management', 'Networking', 'Resilience']
    }
  },
  {
    id: 'chef',
    title: 'Chef',
    category: 'Culinary',
    description: 'Prepare and cook food in restaurants and other food service establishments',
    skills: ['creativity', 'attention_to_detail', 'physical_coordination', 'time_management'],
    interests: ['culinary_arts', 'food', 'creativity'],
    work_environment: ['kitchen', 'restaurant'],
    education_required: 'varies',
    typical_majors: ['Culinary Arts', 'Hospitality Management'],
    salary_range: { min: 30000, max: 80000 },
    growth_outlook: 'Good',
    work_style: ['team'],
    personality_traits: ['creative', 'detail_oriented', 'passionate'],
    values_alignment: ['creativity', 'task_variety', 'passion'],
    skills_gap_analysis: {
      technical: ['Cooking techniques', 'Food safety', 'Menu planning', 'Kitchen management'],
      soft_skills: ['Creativity', 'Time management', 'Teamwork', 'Stress management']
    }
  },
  {
    id: 'journalist',
    title: 'Journalist',
    category: 'Media',
    description: 'Research, write, and report news stories for various media outlets',
    skills: ['writing', 'communication', 'research', 'critical_thinking', 'curiosity'],
    interests: ['journalism', 'writing', 'current_events', 'communication'],
    work_environment: ['office', 'field', 'home'],
    education_required: 'bachelors',
    typical_majors: ['Journalism', 'Communications', 'English'],
    salary_range: { min: 35000, max: 80000 },
    growth_outlook: 'Moderate',
    work_style: ['individual', 'team'],
    personality_traits: ['curious', 'persistent', 'communicative'],
    values_alignment: ['truth', 'public_service', 'creativity'],
    skills_gap_analysis: {
      technical: ['Writing', 'Research', 'Digital media', 'Interviewing'],
      soft_skills: ['Communication', 'Critical thinking', 'Ethics', 'Adaptability']
    }
  },
  {
    id: 'architect',
    title: 'Architect',
    category: 'Design',
    description: 'Design buildings and structures that are functional, safe, and aesthetically pleasing',
    skills: ['creativity', 'mathematics', 'attention_to_detail', 'visual_interpretation', 'problem_solving'],
    interests: ['architecture', 'design', 'building', 'creativity'],
    work_environment: ['office', 'field'],
    education_required: 'bachelors',
    typical_majors: ['Architecture', 'Design'],
    salary_range: { min: 60000, max: 120000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['creative', 'detail_oriented', 'visionary'],
    values_alignment: ['creativity', 'aesthetics', 'functionality'],
    skills_gap_analysis: {
      technical: ['Design software', 'Building codes', 'Structural engineering', 'Project management'],
      soft_skills: ['Creativity', 'Communication', 'Problem solving', 'Client relations']
    }
  },
  {
    id: 'environmental_scientist',
    title: 'Environmental Scientist',
    category: 'Science',
    description: 'Study environmental problems and develop solutions to protect the environment',
    skills: ['research', 'analytical_thinking', 'attention_to_detail', 'problem_solving'],
    interests: ['environmental_science', 'nature', 'conservation', 'science'],
    work_environment: ['field', 'lab', 'office'],
    education_required: 'bachelors',
    typical_majors: ['Environmental Science', 'Biology', 'Chemistry'],
    salary_range: { min: 50000, max: 100000 },
    growth_outlook: 'Excellent',
    work_style: ['individual', 'team'],
    personality_traits: ['environmentally_conscious', 'analytical', 'passionate'],
    values_alignment: ['environmental_protection', 'social_impact', 'meaningful_causes'],
    skills_gap_analysis: {
      technical: ['Environmental assessment', 'Data analysis', 'Field sampling', 'GIS software'],
      soft_skills: ['Communication', 'Problem solving', 'Collaboration', 'Advocacy']
    }
  },
  {
    id: 'police_officer',
    title: 'Police Officer',
    category: 'Public Safety',
    description: 'Maintain public safety and enforce laws in communities',
    skills: ['communication', 'physical_fitness', 'decision_making', 'attention_to_detail'],
    interests: ['public_safety', 'justice', 'helping_others'],
    work_environment: ['field', 'office'],
    education_required: 'varies',
    typical_majors: ['Criminal Justice', 'Law Enforcement'],
    salary_range: { min: 40000, max: 80000 },
    growth_outlook: 'Good',
    work_style: ['team'],
    personality_traits: ['responsible', 'courageous', 'empathetic'],
    values_alignment: ['public_service', 'justice', 'helping_others'],
    skills_gap_analysis: {
      technical: ['Law enforcement', 'Self-defense', 'Investigation', 'Emergency response'],
      soft_skills: ['Communication', 'Conflict resolution', 'Physical fitness', 'Ethics']
    }
  },
  {
    id: 'firefighter',
    title: 'Firefighter',
    category: 'Public Safety',
    description: 'Respond to fires and other emergencies to protect people and property',
    skills: ['physical_fitness', 'teamwork', 'decision_making', 'courage'],
    interests: ['public_safety', 'helping_others', 'physical_work'],
    work_environment: ['field', 'fire_station'],
    education_required: 'varies',
    typical_majors: ['Fire Science', 'Emergency Management'],
    salary_range: { min: 35000, max: 70000 },
    growth_outlook: 'Good',
    work_style: ['team'],
    personality_traits: ['courageous', 'physically_fit', 'team_oriented'],
    values_alignment: ['public_service', 'helping_others', 'adventure'],
    skills_gap_analysis: {
      technical: ['Fire suppression', 'Emergency response', 'Equipment operation', 'First aid'],
      soft_skills: ['Teamwork', 'Physical fitness', 'Courage', 'Quick thinking']
    }
  },
  {
    id: 'pilot',
    title: 'Pilot',
    category: 'Transportation',
    description: 'Fly aircraft to transport passengers and cargo',
    skills: ['attention_to_detail', 'decision_making', 'spatial_awareness', 'communication'],
    interests: ['aviation', 'travel', 'technology'],
    work_environment: ['aircraft', 'airport'],
    education_required: 'varies',
    typical_majors: ['Aviation', 'Aeronautical Engineering'],
    salary_range: { min: 60000, max: 200000 },
    growth_outlook: 'Good',
    work_style: ['individual', 'team'],
    personality_traits: ['responsible', 'detail_oriented', 'calm_under_pressure'],
    values_alignment: ['adventure', 'travel', 'high_salary'],
    skills_gap_analysis: {
      technical: ['Flight training', 'Aircraft systems', 'Navigation', 'Weather analysis'],
      soft_skills: ['Decision making', 'Communication', 'Stress management', 'Leadership']
    }
  }
];

module.exports = careers; 