"""Client and candidate configuration definitions.

Defines target candidate profiles, search roles, exclusion keywords,
C2C bench-marketing filters, and client data models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# C2C & Bench Marketing Spam Filter Keywords
BENCH_MARKETING_PHRASES: list[str] = [
    "on my bench",
    "on our bench",
    "consultant available",
    "candidate available",
    "marketing my consultant",
    "marketing consultant",
    "hotlist",
    "available consultants",
    "immediate available for",
    "consultants available",
    "looking for c2c requirements",
    "share your c2c requirements",
    "send c2c requirements",
]

# Non-USA Indicators (Geo filter reject list)
NON_USA_INDICATORS: list[str] = [
    "pune",
    "noida",
    "bangalore",
    "bengaluru",
    "hyderabad",
    "chennai",
    "mumbai",
    "delhi",
    "gurgaon",
    "gurugram",
    "kolkata",
    "ahmedabad",
    "india",
    "canada",
    "toronto",
    "vancouver",
    "uk",
    "london",
    "australia",
    "sydney",
    "melbourne",
    "dubai",
    "uae",
    "singapore",
]

# Standard US States and Terms (Accepted list)
USA_GEO_INDICATORS: list[str] = [
    "united states",
    "usa",
    "u.s.a",
    "u.s.",
    "remote - us",
    "remote (us",
    "remote, us",
    "us remote",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "texas", "california", "new york", "florida", "illinois",
    "georgia", "north carolina", "ohio", "virginia", "washington",
    "new jersey", "massachusetts", "michigan", "arizona", "colorado",
]


@dataclass
class RoleDefinition:
    """Target role configuration and filtering parameters."""
    primary_role: str
    search_roles: list[str]
    exclusion_keywords: list[str] = field(default_factory=list)


# Defined roles and their corresponding search expressions and domain exclusions
CANDIDATE_ROLES: dict[str, RoleDefinition] = {
    "java_developer": RoleDefinition(
        primary_role="Java Full Stack Developer",
        search_roles=[
            "Java Full Stack Developer",
            "Java Developer",
            "Java Backend Engineer",
            "Senior Java Developer",
        ],
        exclusion_keywords=[
            "devops", "qa", "quality assurance", "tester", "salesforce",
            "ios", "android", "mobile developer", "flutter", "react native",
            "sap", "embedded", "data scientist", "machine learning",
        ],
    ),
    "python_developer": RoleDefinition(
        primary_role="Python Backend Developer",
        search_roles=[
            "Python Developer",
            "Python Backend Engineer",
            "Full Stack Python Engineer",
        ],
        exclusion_keywords=[
            "devops", "qa", "tester", "salesforce", "ios", "android",
            "sap", "embedded", "hardware",
        ],
    ),
    "dotnet_developer": RoleDefinition(
        primary_role=".NET Full Stack Developer",
        search_roles=[
            ".NET Developer",
            "C# .NET Core Engineer",
            ".NET Full Stack Engineer",
        ],
        exclusion_keywords=[
            "devops", "qa", "tester", "salesforce", "ios", "android",
            "sap", "embedded",
        ],
    ),
}


@dataclass
class CandidateProfile:
    """Registered candidate profile for outreach automation."""
    id: str
    name: str
    email: str
    primary_role: str
    experience_years: int
    resume_path: str
    skills: list[str]
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    customizer_module: Optional[str] = None  # e.g. "safi_customizer" or None for generic

    def get_absolute_resume_path(self, base_dir: Optional[Path] = None) -> Path:
        """Resolve absolute path to candidate resume."""
        p = Path(self.resume_path)
        if p.is_absolute():
            return p
        base = base_dir or Path.cwd()
        return (base / p).resolve()


# Registered Clients / Candidates list
# Includes dummy example candidate for testing and validation
CLIENTS: list[CandidateProfile] = [
    CandidateProfile(
        id="alex_johnson_dummy",
        name="Alex Johnson",
        email="alex.johnson.test@example.com",
        primary_role="Java Full Stack Developer",
        experience_years=8,
        resume_path="clients/resumes/dummy_alex_johnson.docx",
        skills=[
            "Java", "Spring Boot", "Microservices", "REST API",
            "PostgreSQL", "React", "Docker", "AWS", "Kafka", "Hibernate",
        ],
        phone="+1-555-019-2831",
        customizer_module=None,
    ),
]


def get_candidate_by_id(candidate_id: str) -> Optional[CandidateProfile]:
    """Retrieve candidate profile by ID."""
    for c in CLIENTS:
        if c.id == candidate_id:
            return c
    return None


def get_role_definition(role_key: str) -> Optional[RoleDefinition]:
    """Retrieve role definition by key."""
    return CANDIDATE_ROLES.get(role_key)
