from pathlib import Path

# --- Path Definitions (relative to this file if used for default paths within DEFAULT_CONFIG) ---
# If ROOT_PATH is needed by other parts of the app, it might be better in a more central util
# or defined where used. For now, keeping it here as it's primarily for default config paths.
APP_DIR = Path(__file__).resolve().parent.parent # src/app/  (resolves to /app/src/app inside container)
PROJECT_ROOT = APP_DIR.parent.parent # genai-crops-analyzer/ (resolves to /app/ inside container)

# --- Default Prompts and Templates (specific to analysis services) ---
DEFAULT_SYSTEM_PROMPT_FOR_REASONING = """You are an expert agricultural consultant specializing in plant pathology and nutrient management.
Your task is to analyze images of crops and provide detailed diagnostic information.
Focus on identifying:
1. Nutrient deficiencies (N, P, K, Ca, Mg, S, Fe, etc.)
2. Diseases (bacterial, fungal, viral)
3. Pest damage
4. Environmental stress (drought, heat, cold, etc.)
5. Growth stage assessment

Provide specific, actionable recommendations for farmers based on your observations.
Your analysis should be concise, technical but understandable, and focused on agricultural insights."""

DEFAULT_PROMPT_TEMPLATE_FOR_REASONING = """Image Caption: {caption}

Affected Area: Approximately {affected_percentage:.1f}% of the plant shows signs of stress or damage.

Based on this information, please provide:
1. A diagnosis of the most likely issues affecting this plant
2. Potential causes of these symptoms
3. Recommended treatments or interventions
4. Preventative measures for the future"""

# --- Default Application Configuration ---
DEFAULT_CONFIG = {
    "app": {
        "name": "GenAI Crops Analyzer",
        "version": "0.1.1",
        "dev_mode": False,
        "cors_origins": [
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:8080",
        ]
    },
    "chat_llm": {
        "model_name": "gemma:2b",
        "ollama_endpoint": "http://localhost:11434",
        "max_tokens": 2000,
        "temperature": 0.7,
        "system_prompt": "You are a helpful agricultural assistant."
    },
    "agent_llm": {
        "model_name": "gemma:2b",
        "ollama_endpoint": "http://localhost:11434",
        "system_prompt": "Eres un agente de Langchain para análisis agrícola. Puedes usar herramientas para responder preguntas.",
        "tools_enabled": ["get_report_history"],
        "tool_messages": {
            "reports_summary_header": "Aquí hay un resumen de los reportes más recientes:",
            "reports_summary_none_found": "No se encontraron reportes.",
            "report_detail_prefix": "- Reporte ID: {report_id}, Creado: {created_at}",
            "report_detail_crop": ", Cultivo: {crop_name}",
            "report_detail_image": ", Imagen: {image_filename}",
            "report_detail_finding": " - Hallazgo: {finding}",
            "report_detail_summary": " - Resumen: {summary}",
            "report_detail_no_details": " - (Detalles no disponibles)"
        }
    },
    "storage": {
        # As per project-rules, default to temp_test_images for local if it exists, else data/images
        # Paths here are relative to PROJECT_ROOT or absolute.
        # The load_app_config in src/__init__.py will handle making them absolute if relative.
        "base_data_path": "temp_test_images" if (PROJECT_ROOT / "temp_test_images").is_dir() else "/tmp/agroai_images"
    },
    "auth": {
        "secret_key": "super-secret-key",
        "algorithm": "HS256",
        "access_token_expire_minutes": 60
    },
    "analysis_services": {
        "unet": {
            "model_endpoint": "http://localhost:8080/predictions/unet-plants",
        },
        "blip": {
            "model_name": "Salesforce/blip2-opt-2.7b",
            "device": "cpu",
            "max_new_tokens": 50,
            "lightweight": False,
            "lightweight_model_name": "Salesforce/blip-image-captioning-base",
        },
        "blip_container": {
            "service_url": "http://localhost:8000",
            "timeout": 30,
            "use_container": False,
        },
        "reasoning_llm": {
            "model_name": "gemma:2b",
            "ollama_endpoint": "http://localhost:11434/api/generate",
            "max_tokens": 1000,
            "temperature": 0.7,
            "system_prompt": DEFAULT_SYSTEM_PROMPT_FOR_REASONING,
            "lightweight_model": "gemma:2b",
            "prompt_template": DEFAULT_PROMPT_TEMPLATE_FOR_REASONING,
        }
    },
    "database": {
        "url": "postgresql+asyncpg://genai_user:genai_password@localhost:54321/genai_reports_db",
        "echo": False
    },
    "timescale": {
        "url": "postgresql+asyncpg://genai_user:genai_password@localhost:54320/genai_reports_db",
        "echo": False
    }
} 