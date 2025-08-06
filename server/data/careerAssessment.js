// Comprehensive Career Assessment System
// 100 questions covering academic background, work style, interests, values, skills, and future goals

const careerAssessment = {
  sections: [
    {
      id: 'academic',
      title: 'Academic & Educational Background',
      description: 'Understanding your educational foundation and learning preferences',
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
        },
        {
          id: 'weakest_subjects',
          question: 'What subjects do you find most challenging?',
          type: 'multiselect',
          options: [
            { value: 'math', label: 'Mathematics' },
            { value: 'science', label: 'Science' },
            { value: 'english', label: 'English/Language Arts' },
            { value: 'history', label: 'History/Social Studies' },
            { value: 'foreign_language', label: 'Foreign Languages' },
            { value: 'arts', label: 'Arts' },
            { value: 'physical_education', label: 'Physical Education' },
            { value: 'none', label: 'None - I do well in all subjects' }
          ]
        },
        {
          id: 'learning_style',
          question: 'What is your preferred learning style?',
          type: 'select',
          options: [
            { value: 'visual', label: 'Visual - I learn best through diagrams, charts, and visual aids' },
            { value: 'auditory', label: 'Auditory - I learn best through listening and discussion' },
            { value: 'kinesthetic', label: 'Hands-on - I learn best through doing and practical experience' },
            { value: 'reading', label: 'Reading/Writing - I learn best through text and written materials' },
            { value: 'group', label: 'Group work - I learn best through collaboration with others' },
            { value: 'independent', label: 'Independent study - I learn best working alone' }
          ]
        },
        {
          id: 'study_habits',
          question: 'How do you typically study?',
          type: 'select',
          options: [
            { value: 'last_minute', label: 'Last-minute cramming before tests' },
            { value: 'daily', label: 'Steady daily work and review' },
            { value: 'group', label: 'Group study sessions with classmates' },
            { value: 'solo', label: 'Solo study in quiet environments' },
            { value: 'mixed', label: 'A combination of different approaches' }
          ]
        },
        {
          id: 'test_performance',
          question: 'How do you typically perform on different types of assessments?',
          type: 'select',
          options: [
            { value: 'tests_better', label: 'I perform better on tests and exams' },
            { value: 'projects_better', label: 'I perform better on projects and assignments' },
            { value: 'multiple_choice', label: 'I do well on multiple choice and objective tests' },
            { value: 'essays', label: 'I do well on essays and written assignments' },
            { value: 'presentations', label: 'I do well on presentations and oral assessments' },
            { value: 'consistent', label: 'I perform consistently across all types of assessments' }
          ]
        },
        {
          id: 'academic_goals',
          question: 'What are your academic goals?',
          type: 'select',
          options: [
            { value: 'just_pass', label: 'Just pass and graduate' },
            { value: 'good_grades', label: 'Get good grades (B average or better)' },
            { value: 'top_class', label: 'Be at the top of my class' },
            { value: 'learning', label: 'Learn and understand the material deeply' },
            { value: 'college_prep', label: 'Prepare for college and future career' }
          ]
        },
        {
          id: 'favorite_assignments',
          question: 'What types of assignments do you enjoy most?',
          type: 'multiselect',
          options: [
            { value: 'research_papers', label: 'Research papers and essays' },
            { value: 'presentations', label: 'Presentations and public speaking' },
            { value: 'lab_work', label: 'Lab work and experiments' },
            { value: 'creative_projects', label: 'Creative projects and artistic work' },
            { value: 'group_projects', label: 'Group projects and collaboration' },
            { value: 'problem_solving', label: 'Problem-solving and analytical work' },
            { value: 'debates', label: 'Debates and discussions' },
            { value: 'field_trips', label: 'Field trips and hands-on experiences' }
          ]
        },
        {
          id: 'class_participation',
          question: 'How do you typically participate in class?',
          type: 'select',
          options: [
            { value: 'active', label: 'Active participant - I speak up frequently' },
            { value: 'quiet', label: 'Quiet observer - I listen and observe' },
            { value: 'questions', label: 'I ask lots of questions' },
            { value: 'answers', label: 'I answer questions when called on' },
            { value: 'discussions', label: 'I contribute to discussions when comfortable' },
            { value: 'minimal', label: 'I prefer minimal participation' }
          ]
        },
        {
          id: 'academic_interests',
          question: 'What academic interests do you pursue outside of required classes?',
          type: 'multiselect',
          options: [
            { value: 'extra_reading', label: 'Extra reading and research' },
            { value: 'online_courses', label: 'Online courses and tutorials' },
            { value: 'documentaries', label: 'Educational documentaries and videos' },
            { value: 'academic_clubs', label: 'Academic clubs and competitions' },
            { value: 'mentorship', label: 'Mentorship or tutoring programs' },
            { value: 'summer_programs', label: 'Summer academic programs' },
            { value: 'none', label: 'I don\'t pursue additional academic interests' }
          ]
        },
        {
          id: 'planned_major',
          question: 'What is your planned college major?',
          type: 'select',
          options: [
            { value: 'computer_science', label: 'Computer Science' },
            { value: 'engineering', label: 'Engineering' },
            { value: 'business', label: 'Business' },
            { value: 'psychology', label: 'Psychology' },
            { value: 'biology', label: 'Biology' },
            { value: 'chemistry', label: 'Chemistry' },
            { value: 'physics', label: 'Physics' },
            { value: 'mathematics', label: 'Mathematics' },
            { value: 'english', label: 'English' },
            { value: 'history', label: 'History' },
            { value: 'political_science', label: 'Political Science' },
            { value: 'economics', label: 'Economics' },
            { value: 'art', label: 'Art' },
            { value: 'music', label: 'Music' },
            { value: 'nursing', label: 'Nursing' },
            { value: 'education', label: 'Education' },
            { value: 'communications', label: 'Communications' },
            { value: 'undecided', label: 'Undecided' }
          ]
        },
        {
          id: 'career_interest',
          question: 'Do you have any career field interests?',
          type: 'select',
          options: [
            { value: 'technology', label: 'Technology and IT' },
            { value: 'healthcare', label: 'Healthcare and Medicine' },
            { value: 'business', label: 'Business and Finance' },
            { value: 'education', label: 'Education and Teaching' },
            { value: 'arts', label: 'Arts and Creative Fields' },
            { value: 'science', label: 'Science and Research' },
            { value: 'law', label: 'Law and Legal Services' },
            { value: 'engineering', label: 'Engineering' },
            { value: 'social_work', label: 'Social Work and Counseling' },
            { value: 'government', label: 'Government and Public Service' },
            { value: 'exploring', label: 'Still exploring options' }
          ]
        },
        {
          id: 'advanced_courses',
          question: 'What advanced courses have you taken?',
          type: 'multiselect',
          options: [
            { value: 'ap_courses', label: 'AP (Advanced Placement) courses' },
            { value: 'ib_courses', label: 'IB (International Baccalaureate) courses' },
            { value: 'honors', label: 'Honors courses' },
            { value: 'dual_enrollment', label: 'Dual enrollment college courses' },
            { value: 'none', label: 'No advanced courses' }
          ]
        },
        {
          id: 'academic_achievements',
          question: 'What academic achievements have you earned?',
          type: 'multiselect',
          options: [
            { value: 'honor_roll', label: 'Honor roll' },
            { value: 'academic_awards', label: 'Academic awards or scholarships' },
            { value: 'competitions', label: 'Academic competitions' },
            { value: 'publications', label: 'Published work or research' },
            { value: 'leadership', label: 'Academic leadership positions' },
            { value: 'none', label: 'No specific academic achievements' }
          ]
        },
        {
          id: 'educational_goals',
          question: 'What are your educational goals beyond high school?',
          type: 'select',
          options: [
            { value: 'bachelors', label: 'Bachelor\'s degree' },
            { value: 'masters', label: 'Master\'s degree' },
            { value: 'doctorate', label: 'Doctorate or PhD' },
            { value: 'professional', label: 'Professional certification (law, medicine, etc.)' },
            { value: 'associates', label: 'Associate\'s degree' },
            { value: 'trade_school', label: 'Trade school or technical training' },
            { value: 'unsure', label: 'Not sure yet' }
          ]
        }
      ]
    },
    {
      id: 'work_style',
      title: 'Work Style & Environment Preferences',
      description: 'Understanding how you prefer to work and what environments suit you best',
      questions: [
        {
          id: 'team_individual',
          question: 'How do you prefer to work?',
          type: 'select',
          options: [
            { value: 'team', label: 'I love teamwork and collaboration' },
            { value: 'individual', label: 'I prefer to work independently' },
            { value: 'depends', label: 'It depends on the project and team' },
            { value: 'mixed', label: 'I enjoy a mix of both' }
          ]
        },
        {
          id: 'leadership_comfort',
          question: 'How comfortable are you with leadership roles?',
          type: 'select',
          options: [
            { value: 'natural_leader', label: 'I\'m a natural leader and enjoy taking charge' },
            { value: 'prefer_follow', label: 'I prefer to follow and support others' },
            { value: 'situational', label: 'I can lead when needed but don\'t always seek it' },
            { value: 'developing', label: 'I\'m developing my leadership skills' }
          ]
        },
        {
          id: 'structure_flexibility',
          question: 'What type of work environment do you prefer?',
          type: 'select',
          options: [
            { value: 'structured', label: 'Clear rules, procedures, and structure' },
            { value: 'flexible', label: 'Freedom to work how I want' },
            { value: 'balanced', label: 'A balance of structure and flexibility' },
            { value: 'adaptive', label: 'I can adapt to different environments' }
          ]
        },
        {
          id: 'workplace_environment',
          question: 'What type of workplace environment do you prefer?',
          type: 'multiselect',
          options: [
            { value: 'office', label: 'Traditional office setting' },
            { value: 'outdoors', label: 'Outdoor or field work' },
            { value: 'home', label: 'Remote work from home' },
            { value: 'lab', label: 'Laboratory or research setting' },
            { value: 'classroom', label: 'Classroom or educational setting' },
            { value: 'hospital', label: 'Healthcare or hospital setting' },
            { value: 'studio', label: 'Creative studio or workshop' },
            { value: 'factory', label: 'Industrial or manufacturing setting' }
          ]
        },
        {
          id: 'interaction_level',
          question: 'How much interaction with people do you want in your work?',
          type: 'select',
          options: [
            { value: 'lots', label: 'Lots of people contact and interaction' },
            { value: 'small_groups', label: 'Small groups and teams' },
            { value: 'mostly_alone', label: 'Mostly working alone' },
            { value: 'mixed', label: 'A mix of interaction and independent work' }
          ]
        },
        {
          id: 'competition_collaboration',
          question: 'How do you feel about competition vs collaboration?',
          type: 'select',
          options: [
            { value: 'competition', label: 'I thrive on competition and challenges' },
            { value: 'collaboration', label: 'I prefer cooperation and collaboration' },
            { value: 'both', label: 'I enjoy both competition and collaboration' },
            { value: 'neither', label: 'I prefer to avoid both' }
          ]
        },
        {
          id: 'pressure_deadlines',
          question: 'How do you handle pressure and deadlines?',
          type: 'select',
          options: [
            { value: 'thrive_pressure', label: 'I work well under pressure and tight deadlines' },
            { value: 'steady_pace', label: 'I prefer a steady, predictable pace' },
            { value: 'mixed', label: 'I can handle some pressure but prefer balance' },
            { value: 'low_pressure', label: 'I work best in low-pressure environments' }
          ]
        },
        {
          id: 'decision_making',
          question: 'What is your decision-making style?',
          type: 'select',
          options: [
            { value: 'quick', label: 'I make quick decisions based on intuition' },
            { value: 'thorough', label: 'I prefer thorough analysis before deciding' },
            { value: 'group', label: 'I prefer group consensus and discussion' },
            { value: 'data_driven', label: 'I rely heavily on data and facts' }
          ]
        },
        {
          id: 'risk_tolerance',
          question: 'What is your risk tolerance in work situations?',
          type: 'select',
          options: [
            { value: 'high', label: 'I love new challenges and taking risks' },
            { value: 'low', label: 'I prefer proven methods and stability' },
            { value: 'calculated', label: 'I take calculated risks after careful consideration' },
            { value: 'moderate', label: 'I\'m comfortable with moderate risk' }
          ]
        },
        {
          id: 'work_schedule',
          question: 'What type of work schedule do you prefer?',
          type: 'select',
          options: [
            { value: 'regular', label: 'Regular 9-5 hours' },
            { value: 'flexible', label: 'Flexible schedule with some choice' },
            { value: 'varied', label: 'Varied timing and shifts' },
            { value: 'part_time', label: 'Part-time or reduced hours' }
          ]
        },
        {
          id: 'physical_mental',
          question: 'What type of work activities do you prefer?',
          type: 'select',
          options: [
            { value: 'physical', label: 'Hands-on, physical activities' },
            { value: 'mental', label: 'Thinking, analysis, and mental work' },
            { value: 'combination', label: 'A combination of physical and mental work' },
            { value: 'creative', label: 'Creative and artistic activities' }
          ]
        },
        {
          id: 'helping_orientation',
          question: 'How do you feel about helping others in your work?',
          type: 'select',
          options: [
            { value: 'direct_service', label: 'I want to provide direct service to people' },
            { value: 'behind_scenes', label: 'I prefer behind-the-scenes support' },
            { value: 'not_priority', label: 'Helping others is not a priority' },
            { value: 'depends', label: 'It depends on the situation' }
          ]
        },
        {
          id: 'detail_big_picture',
          question: 'What is your focus preference?',
          type: 'select',
          options: [
            { value: 'details', label: 'I love working with details and precision' },
            { value: 'big_picture', label: 'I prefer big picture thinking and strategy' },
            { value: 'both', label: 'I need both details and big picture' },
            { value: 'depends', label: 'It depends on the project' }
          ]
        },
        {
          id: 'routine_variety',
          question: 'How do you feel about routine vs variety?',
          type: 'select',
          options: [
            { value: 'routine', label: 'I enjoy routine and predictable work' },
            { value: 'variety', label: 'I need constant change and variety' },
            { value: 'some_both', label: 'I like some routine with occasional variety' },
            { value: 'balanced', label: 'I prefer a balanced approach' }
          ]
        },
        {
          id: 'problem_solving',
          question: 'What is your problem-solving approach?',
          type: 'select',
          options: [
            { value: 'methodical', label: 'Methodical steps and systematic analysis' },
            { value: 'creative', label: 'Creative brainstorming and innovative thinking' },
            { value: 'trial_error', label: 'Trial and error with experimentation' },
            { value: 'collaborative', label: 'Collaborative problem-solving with others' }
          ]
        },
        {
          id: 'communication_preference',
          question: 'What is your preferred communication method?',
          type: 'select',
          options: [
            { value: 'written', label: 'Written communication (email, reports, documents)' },
            { value: 'verbal', label: 'Verbal communication (meetings, phone calls)' },
            { value: 'visual', label: 'Visual communication (presentations, charts, graphics)' },
            { value: 'mixed', label: 'A mix of different communication methods' }
          ]
        },
        {
          id: 'feedback_comfort',
          question: 'How do you feel about receiving feedback?',
          type: 'select',
          options: [
            { value: 'love_feedback', label: 'I love feedback and actively seek it' },
            { value: 'prefer_independence', label: 'I prefer to work independently without feedback' },
            { value: 'constructive', label: 'I appreciate constructive feedback' },
            { value: 'occasional', label: 'I like occasional feedback but not constant' }
          ]
        },
        {
          id: 'training_teaching',
          question: 'How do you feel about training or teaching others?',
          type: 'select',
          options: [
            { value: 'enjoy_explaining', label: 'I enjoy explaining and teaching others' },
            { value: 'prefer_not', label: 'I prefer not to teach or train others' },
            { value: 'depends', label: 'It depends on the situation and topic' },
            { value: 'developing', label: 'I\'m developing my teaching skills' }
          ]
        },
        {
          id: 'travel_work',
          question: 'How do you feel about travel for work?',
          type: 'select',
          options: [
            { value: 'love_travel', label: 'I love to travel and see new places' },
            { value: 'prefer_local', label: 'I prefer staying local and close to home' },
            { value: 'occasional', label: 'Occasional travel is okay' },
            { value: 'no_travel', label: 'I prefer no travel for work' }
          ]
        },
        {
          id: 'technology_comfort',
          question: 'How comfortable are you with technology?',
          type: 'select',
          options: [
            { value: 'early_adopter', label: 'I\'m an early adopter of new technology' },
            { value: 'comfortable_user', label: 'I\'m a comfortable user of current technology' },
            { value: 'minimal_tech', label: 'I prefer minimal technology use' },
            { value: 'learning', label: 'I\'m learning and becoming more comfortable with technology' }
          ]
        }
      ]
    }
  ]
};

module.exports = careerAssessment; 