"""
All agent prompts, in one place: no service, tool or runner writes text for the model inline.

Each module holds the system instruction of an invocation (`*_INSTRUCTION`, in the same sections: Rol, Qué recibís,
Qué hacer, Reglas, Formato de salida) and the `build_*_prompt` functions that turn data into the user message.

Index (invocation → module):
- Chat agent (AgentRunner): chat.py (+ voice.py for the voice by country, knowledge*.py for regional facts)
- Preflight router of a chat turn (preflight/engine.py): preflight.py
- Conversation title: title.py
- Voice note transcription (GeminiGateway.transcribe): transcription.py
- Expert field analysis (tools/analysis.py): expert.py
- Single-photo diagnosis: diagnosis.py
- Periodic tracking of one crop, and the zone's daily tracking (overview, groups, synthesis): periodic.py
- Evolution of the zone's follow-ups: followups.py
- Soil-sample photo: soil.py
- Harvest verdict and plant count from a photo: harvest.py
- Grounding, reference material and the deep refine pass shared by the analyses: analysis.py
- NDVI map and satellite series: satellite.py
- Layout drawn from a photo (tools/layout.py): farm.py
- Proactive check (agent/nudges.py): nudges.py
- Morning summary of each field (agent/digests.py): digests.py
"""
