# src/app/analysis/domain/parsers.py
import json
from typing import Dict, Any

from src.app.utils.logger import get_logger

logger = get_logger(__name__)

def parse_llm_diagnosis_output(llm_output_str: str) -> Dict[str, Any]:
    """
    Parses the raw string output from an LLM, expecting a JSON object.
    Cleans common markdown code block fences (```json ... ```) if present.

    Args:
        llm_output_str: The raw string output from the LLM.

    Returns:
        A dictionary parsed from the JSON string.
        Returns an empty dictionary if the input is empty, cannot be parsed,
        or after cleaning results in an empty string.
    """
    if not llm_output_str:
        logger.warning("LLM output string is empty. Returning empty dict.")
        return {}

    clean_str = llm_output_str.strip()

    if clean_str.startswith("```json"):
        clean_str = clean_str[7:] # Remove ```json
    if clean_str.endswith("```"):
        clean_str = clean_str[:-3] # Remove ```
    
    clean_str = clean_str.strip()

    if not clean_str:
        logger.warning("LLM output string is empty after cleaning. Returning empty dict.")
        return {}

    try:
        parsed_json = json.loads(clean_str)
        if not isinstance(parsed_json, dict):
            logger.warning(f"Parsed JSON is not a dictionary. LLM Output: '{llm_output_str}'. Parsed: '{parsed_json}'")
            return {}
        return parsed_json
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM diagnosis JSON: {e}. Raw output: '{llm_output_str}'")
        return {} # Or raise specific parsing error 