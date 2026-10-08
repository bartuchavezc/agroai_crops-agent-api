"""Country-aware entry points for the knowledge modules and the profile styles (Argentina by default)."""
from typing import Optional

from src.auth.services.profile_calculator import ProfileType

from . import knowledge_ar, knowledge_mx


def modules_for(country: Optional[str], profile: Optional[ProfileType], crop_families: set[str],
                field_texts: list[str]) -> str:
    """Facts for the account: the regional module set of its country, plus what its crops call for."""
    if country == "MX":
        return knowledge_mx.modules_for_account_mx(profile, crop_families, field_texts)
    return knowledge_ar.modules_for_account(profile, crop_families, field_texts)


def style_for(profile: Optional[ProfileType]) -> str:
    """How to behave for the onboarding profile. Country-neutral; the voice block says how to word it."""
    return knowledge_ar.style_for_profile(profile)
