"""Country-aware entry points for the knowledge modules and the profile styles (Argentina by default)."""
from typing import Optional

from src.auth.services.profile_calculator import ProfileType

from . import knowledge_ar, knowledge_co, knowledge_mx


def modules_for(country: Optional[str], profile: Optional[ProfileType], crop_families: set[str],
                field_texts: list[str]) -> str:
    """Facts for the account: the regional module set of its country, plus what its crops call for."""
    if country == "MX":
        return knowledge_mx.modules_for_account_mx(profile, crop_families, field_texts)
    if country == "CO":
        return knowledge_co.modules_for_account_co(profile, crop_families, field_texts)
    return knowledge_ar.modules_for_account(profile, crop_families, field_texts)


def style_for(profile: Optional[ProfileType]) -> str:
    """How to behave for the onboarding profile. Country-neutral; the voice block says how to word it."""
    return knowledge_ar.style_for_profile(profile)


def intensity_for(intensity: Optional[str]) -> str:
    """How hard to push for checks, by the person's chosen tracking intensity (baja | media | alta)."""
    return knowledge_ar.intensity_prompt(intensity)


def short_style(profile: Optional[ProfileType]) -> str:
    """The communication guide of a profile without its heading, for prompts that address several people."""
    text = style_for(profile)
    return text.split("\n", 1)[1].strip() if "\n" in text else text
