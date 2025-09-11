import numpy as np
import requests
from typing import Optional
import json

from .reasoning_repository import ReasoningRepository
from src.app.analysis.domain.models import StructuredDiagnosis


class MistralRepository(ReasoningRepository):
    """
    Mistral LLM implementation of the reasoning repository.
    
    This class provides agricultural reasoning functionality using Mistral LLM,
    served locally via Ollama.
    """
    
    def __init__(
        self,
        model_name: Optional[str] = None,
        ollama_endpoint: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        prompt_template: Optional[str] = None
    ):
        """
        Initialize the Mistral reasoning repository.
        
        Args:
            model_name (Optional[str]): Name of the Mistral model variant to use
            ollama_endpoint (Optional[str]): Endpoint for Ollama API
            max_tokens (Optional[int]): Maximum number of tokens to generate
            temperature (Optional[float]): Temperature for generation (higher = more creative)
            system_prompt (Optional[str]): System prompt to guide the LLM
            prompt_template (Optional[str]): Prompt template for constructing LLM prompts (unused here but good for consistency)
        """
        self.model_name = model_name
        self.ollama_endpoint = ollama_endpoint
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = system_prompt

    def generate_from_prompt(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate a response from the LLM using the provided prompt.
        
        Args:
            prompt (str): The complete prompt for the LLM
            system_prompt (Optional[str]): Optional system prompt to override the default
            
        Returns:
            str: Generated response from the LLM
        """
        # Use provided system prompt or the default one
        system = system_prompt or self.system_prompt
        
        return self._call_llm(prompt, system)
    
    def analyze(
        self, 
        image: np.ndarray, 
        segmentation_mask: np.ndarray, 
        caption: str,
        affected_percentage: Optional[float] = None
    ) -> str:
        """
        Analyze an image using Mistral LLM to generate agricultural insights.
        The response should be a JSON string conforming to the StructuredDiagnosis model.
        
        Args:
            image (np.ndarray): Original image as numpy array
            segmentation_mask (np.ndarray): Segmentation mask highlighting regions of interest
            caption (str): Caption describing the image, from the captioner service
            affected_percentage (Optional[float]): Percentage of the plant affected by issues,
                calculated by the segmenter service
            
        Returns:
            str: JSON string with agricultural analysis and diagnostic text, 
                 conforming to StructuredDiagnosis.
        """
        if affected_percentage is None:
            affected_percentage = self._calculate_affected_percentage(segmentation_mask)

        # Get the JSON schema and example from the Pydantic model
        schema = StructuredDiagnosis.model_json_schema()
        example_json = StructuredDiagnosis.model_config['json_schema_extra']['example']
        
        # Convert example to a compact JSON string to include in the prompt
        example_json_str = json.dumps(example_json)

        prompt = f"""Analyze the following plant's condition based on the provided information.
The plant is described as: "{caption}".
Approximately {affected_percentage:.1f}% of the plant shows signs of stress or damage according to a segmentation analysis.

Your response MUST be a valid JSON object that conforms to the following JSON schema.
Do NOT include any text outside the JSON object, not even backticks like \\\`\\\`\\\`json or \\\`\\\`\\\`.

JSON Schema:
```json
{json.dumps(schema, indent=2)}
```

Here is an example of the expected JSON output structure:
```json
{example_json_str}
```

Based on the caption "{caption}" and the affected area of {affected_percentage:.1f}%, provide a comprehensive analysis including:
- A general diagnosis.
- Possible causes.
- Recommended treatments (as a list of objects, each with a 'title' and 'description').
- Preventative measures (as a list of objects, each with a 'title' and 'description').
- Specific recommendations (e.g., fertilization, irrigation, pest monitoring, soil analysis) as a list of objects, each with a 'title' and 'description'.
- Any additional notes.

Ensure all text within the JSON, such as titles and descriptions, is in Spanish. The keys of the JSON object must be in English as specified in the schema.

Now, provide the JSON response:
"""
        
        # The system prompt guides the LLM to act as an agricultural expert
        # and to output structured JSON.
        system_prompt_for_analysis = (
            self.system_prompt or 
            "You are an expert agronomist and plant pathologist. "
            "Your goal is to provide a detailed and actionable analysis of crop health "
            "based on visual and contextual information. "
            "You always respond in valid JSON format, according to the schema provided by the user. "
            "Do not add any extra text before or after the JSON object."
        )
        
        return self.generate_from_prompt(prompt, system_prompt=system_prompt_for_analysis)
    
    def _calculate_affected_percentage(self, mask: np.ndarray) -> float:
        """
        Calculate the percentage of the image affected by issues.
        Used as a fallback if affected_percentage is not provided.
        
        Args:
            mask (np.ndarray): Segmentation mask
            
        Returns:
            float: Percentage of affected area
        """
        if len(mask.shape) == 2:
            # Binary mask
            total_pixels = mask.shape[0] * mask.shape[1]
            affected_pixels = np.sum(mask > 0)
            return (affected_pixels / total_pixels) * 100
        else:
            # Multi-class mask, consider all non-zero classes as affected
            total_pixels = mask.shape[0] * mask.shape[1]
            affected_pixels = np.sum(mask > 0)
            return (affected_pixels / total_pixels) * 100
    
    def _call_llm(self, prompt: str, system_prompt: str = None) -> str:
        """
        Call the Mistral LLM via Ollama API.
        
        Args:
            prompt (str): Formatted prompt for the LLM
            system_prompt (str, optional): Override for the system prompt
            
        Returns:
            str: Generated analysis text
        """
        try:
            # Use provided system prompt or the default one
            system = system_prompt or self.system_prompt
            
            # Prepare the request payload
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "options": {
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens
                }
            }
            
            # Call Ollama API
            response = requests.post(
                self.ollama_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code != 200:
                raise RuntimeError(f"LLM request failed with status {response.status_code}: {response.text}")
            
            result = response.json()
            return result.get("response", "")
            
        except Exception as e:
            raise RuntimeError(f"Error calling LLM endpoint: {str(e)}")