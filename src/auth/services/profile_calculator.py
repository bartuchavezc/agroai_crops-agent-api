# src/auth/services/profile_calculator.py
"""
Profile calculator for user onboarding.

Maps questionnaire responses to user categories and calculates
the dominant profile for agent behavior customization.
"""
from typing import Literal

# Type definitions for clarity
ExperienceLevel = Literal["novice", "intermediate", "expert"]
GoalType = Literal["self_consumption", "local_market", "premium_export"]
RiskLevel = Literal["low", "balanced", "high"]
PhilosophyType = Literal["organic", "integrated", "traditional"]
ProfileType = Literal["guardian", "purist", "alchemist", "professional"]


# Mapping from answer letters to category values
EXPERIENCE_MAP = {
    "A": "novice",
    "B": "intermediate", 
    "C": "expert"
}

GOAL_MAP = {
    "A": "self_consumption",
    "B": "local_market",
    "C": "premium_export"
}

RISK_MAP = {
    "A": "low",
    "B": "balanced",
    "C": "high"
}

PHILOSOPHY_MAP = {
    "A": "organic",
    "B": "integrated",
    "C": "traditional"
}

TECH_MAP = {
    "A": "basic",
    "B": "moderate",
    "C": "advanced"
}


class ProfileCalculator:
    """
    Calculates user profile categories based on onboarding questionnaire responses.
    
    Question mapping:
    - Q1-Q2: Experience (trayectoria + familiaridad técnica)
    - Q3: Goal (destino de frutos)
    - Q4-Q5: Risk (manejo de plagas + estrés de planta)
    - Q6-Q7: Philosophy (agroquímicos + bio-insumos)
    - Q8-Q10: Tech/Innovation (usado para calcular perfil dominante)
    
    Profile calculation:
    - El Guardián: Mayoría "A" (novato, conservador)
    - El Purista: philosophy="organic" + experience="intermediate/expert"
    - El Alquimista: risk="high" + goal="premium_export"
    - El Profesional: experience="expert" + tech="advanced"
    """

    @staticmethod
    def calculate_experience(form: dict) -> ExperienceLevel:
        """
        Calculate experience level from Q1 and Q2.
        Returns the dominant answer or the average.
        """
        q1 = form.get("q1", "A")
        q2 = form.get("q2", "A")
        
        # Convert to numeric for averaging
        score_map = {"A": 1, "B": 2, "C": 3}
        avg = (score_map.get(q1, 1) + score_map.get(q2, 1)) / 2
        
        if avg <= 1.5:
            return "novice"
        elif avg <= 2.5:
            return "intermediate"
        else:
            return "expert"

    @staticmethod
    def calculate_goal(form: dict) -> GoalType:
        """Calculate goal from Q3."""
        q3 = form.get("q3", "A")
        return GOAL_MAP.get(q3, "self_consumption")

    @staticmethod
    def calculate_risk(form: dict) -> RiskLevel:
        """
        Calculate risk tolerance from Q4 and Q5.
        """
        q4 = form.get("q4", "A")
        q5 = form.get("q5", "A")
        
        score_map = {"A": 1, "B": 2, "C": 3}
        avg = (score_map.get(q4, 1) + score_map.get(q5, 1)) / 2
        
        if avg <= 1.5:
            return "low"
        elif avg <= 2.5:
            return "balanced"
        else:
            return "high"

    @staticmethod
    def calculate_philosophy(form: dict) -> PhilosophyType:
        """
        Calculate philosophy from Q6 and Q7.
        """
        q6 = form.get("q6", "A")
        q7 = form.get("q7", "A")
        
        score_map = {"A": 1, "B": 2, "C": 3}
        avg = (score_map.get(q6, 1) + score_map.get(q7, 1)) / 2
        
        if avg <= 1.5:
            return "organic"
        elif avg <= 2.5:
            return "integrated"
        else:
            return "traditional"

    @staticmethod
    def calculate_tech_level(form: dict) -> str:
        """
        Calculate tech/innovation level from Q8, Q9, Q10.
        """
        q8 = form.get("q8", "A")
        q9 = form.get("q9", "A")
        q10 = form.get("q10", "A")
        
        score_map = {"A": 1, "B": 2, "C": 3}
        avg = (score_map.get(q8, 1) + score_map.get(q9, 1) + score_map.get(q10, 1)) / 3
        
        if avg <= 1.5:
            return "basic"
        elif avg <= 2.5:
            return "moderate"
        else:
            return "advanced"

    @classmethod
    def calculate_profile(
        cls,
        experience: ExperienceLevel,
        goal: GoalType,
        risk: RiskLevel,
        philosophy: PhilosophyType,
        form: dict
    ) -> ProfileType:
        """
        Calculate the dominant profile based on categories.
        
        Profile determination (in priority order):
        1. El Profesional: experience="expert" + tech="advanced"
        2. El Alquimista: risk="high" + goal="premium_export"
        3. El Purista: philosophy="organic" + experience in ("intermediate", "expert")
        4. El Guardián: Default for novice/conservative users
        """
        tech_level = cls.calculate_tech_level(form)
        
        # El Profesional: Expert with advanced tech preferences
        if experience == "expert" and tech_level == "advanced":
            return "professional"
        
        # El Alquimista: High risk tolerance + premium export goal
        if risk == "high" and goal == "premium_export":
            return "alchemist"
        
        # El Purista: Organic philosophy with some experience
        if philosophy == "organic" and experience in ("intermediate", "expert"):
            return "purist"
        
        # El Guardián: Default for novice or conservative users
        return "guardian"

    @classmethod
    def calculate_all(cls, form: dict) -> dict:
        """
        Calculate all profile categories from the form.
        
        Args:
            form: Dictionary with q1-q10 answers (A/B/C)
            
        Returns:
            Dictionary with experience, goal, risk, philosophy, and profile
        """
        experience = cls.calculate_experience(form)
        goal = cls.calculate_goal(form)
        risk = cls.calculate_risk(form)
        philosophy = cls.calculate_philosophy(form)
        profile = cls.calculate_profile(experience, goal, risk, philosophy, form)
        
        return {
            "experience": experience,
            "goal": goal,
            "risk": risk,
            "philosophy": philosophy,
            "profile": profile
        }

    @staticmethod
    def get_agent_config(profile: ProfileType, categories: dict) -> dict:
        """
        Generate agent configuration based on the calculated profile.
        
        Args:
            profile: The calculated profile type
            categories: Dictionary with experience, goal, risk, philosophy
            
        Returns:
            Configuration dictionary for agent behavior
        """
        configs = {
            "guardian": {
                "technical_tone": "simple_pedagogic",
                "risk_tolerance": "conservative",
                "sanitary_framework": "preventive",
                "priority": "plant_safety",
                "alert_threshold": "early_warning",
                "instruction_style": "detailed_guide"
            },
            "purist": {
                "technical_tone": "moderate_organic",
                "risk_tolerance": "balanced",
                "sanitary_framework": "biological",
                "priority": "biodiversity",
                "alert_threshold": "balanced",
                "filter_synthetic": True
            },
            "alchemist": {
                "technical_tone": "high_scientific",
                "risk_tolerance": "high_experimental",
                "sanitary_framework": "integrated_management",
                "priority": "quality_optimization",
                "alert_threshold": "critical_only",
                "stress_suggestions": True
            },
            "professional": {
                "technical_tone": "data_driven",
                "risk_tolerance": "calculated",
                "sanitary_framework": "evidence_based",
                "priority": "efficiency",
                "alert_threshold": "data_anomaly",
                "show_raw_data": True,
                "show_graphs": True
            }
        }
        
        config = configs.get(profile, configs["guardian"])
        
        # Add category information to config
        config["experience_level"] = categories.get("experience", "novice")
        config["production_goal"] = categories.get("goal", "self_consumption")
        
        return config
