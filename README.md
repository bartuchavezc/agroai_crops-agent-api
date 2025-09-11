# GenAI Crops Analyzer API

A Flask-based API for analyzing crops using GenAI. This application provides:

- Image preprocessing capabilities for crop analysis
- Video processing with automatic plant segmentation
- GenAI-powered detection of nutrient deficiencies, diseases, and key conditions
- RESTful API for integrating with other applications

## Project Structure

```
genai-crops-analyzer/
├── app/                      # Main application package
│   ├── __init__.py           # Flask application initialization
│   ├── api/                  # API endpoints
│   ├── analysis/             # GenAI analysis modules
│   │   ├── config/           # Configuration settings
│   │   ├── container.py      # Dependency injection container
│   │   ├── dto/              # Data Transfer Objects
│   │   ├── infrastructure/   # Repository implementations
│   │   └── service/          # Service layer
│   └── utils/                # Utility functions
├── data/                     # Data storage (uploads, etc.)
├── tests/                    # Unit and integration tests
├── .env                      # Environment variables (not in version control)
├── .gitignore                # Git ignore file
├── pyproject.toml            # Poetry project configuration
├── README.md                 # Project documentation
└── run.py                    # Entry point for running the application
```

## Setup and Installation

This project uses Poetry for dependency management:

1. Install Poetry (if not already installed):
```
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install dependencies:
```
cd genai-crops-analyzer
poetry install
```

3. Run the application:
```
poetry run python run.py
```

Or with Gunicorn (production):
```
poetry run gunicorn "app:create_app()"
```

## API Endpoints

### Analyze Image
`POST /api/analyze`

Upload an image for analysis of crop diseases and nutrient deficiencies.

**Request:**
- Form data with:
  - `image`: Image file (JPG, PNG)

**Response:**
```json
{
  "status": "success",
  "caption": "A tomato plant with yellow leaves and brown spots",
  "diagnosis": "The plant appears to be suffering from early blight...",
  "segmentation_mask": "base64_encoded_image_data",
  "metadata": {
    "affected_percentage": 35.2
  }
}
```

### Analyze Video
`POST /api/analyze-video`

Upload a video for automatic extraction and analysis of plant images. The API will:
1. Extract frames from the video at specified intervals
2. Detect and segment individual plants from each frame
3. Analyze each plant for diseases and nutrient deficiencies

**Request:**
- Form data with:
  - `video`: Video file (MP4, AVI, MOV, MKV)
  - `frame_interval`: Extract 1 frame every N frames (default: 30)
  - `analysis_type`: Type of analysis to perform (options: "disease", "nutrient", "both")

**Response:**
```json
{
  "video_filename": "unique_filename.mp4",
  "frames_extracted": 10,
  "plants_detected": 25,
  "analysis_results": [
    {
      "plant_image": "frame_20230505_123045_abcd1234_plant_0.jpg",
      "status": "success",
      "diseases": { ... },
      "nutrients": { ... }
    },
    ...
  ],
  "status": "success"
}
```

### Health Check
`GET /api/health`

Check if the API is running.

**Response:**
```json
{
  "status": "healthy"
}
```

## Architecture

This application follows a clean architecture pattern with:

1. **Service Layer**: Coordinates the repositories to perform analysis
2. **Repository Pattern**: Abstracts the AI components (segmentation, captioning, reasoning)
3. **Dependency Injection**: Uses the `dependency-injector` package to manage dependencies

### Dependency Injection

The application uses the `dependency-injector` package to implement the dependency injection pattern, which:

- Decouples components and makes the code more testable
- Centralizes configuration management
- Makes it easier to swap implementations (e.g., for testing or different environments)

The dependency injection container is defined in `app/analysis/container.py` and provides:

- Repository implementations (UNetRepository, Blip2Repository, MistralRepository)
- Services that coordinate these repositories (AnalysisService)

### Example of Service with Injected Dependencies:

```python
class AnalysisService:
    def __init__(
        self,
        segmenter: SegmenterRepository,
        captioner: CaptionerRepository,
        reasoner: ReasoningRepository
    ):
        self.segmenter = segmenter
        self.captioner = captioner
        self.reasoner = reasoner
        
    def analyze_image(self, image: np.ndarray) -> CropReport:
        # Implementation using the injected repositories
```

## Configuration

The system uses a centralized configuration system for all external services. Configuration is managed through environment variables and the `app/analysis/config/services_config.py` file.

### Configuration Settings

- **UNet/TorchServe settings:**
  - `UNET_MODEL_ENDPOINT`: TorchServe endpoint URL for the UNet model

- **BLIP-2 settings:**
  - `BLIP_MODEL_NAME`: Name of the BLIP model to use
  - `BLIP_DEVICE`: Device to run the model on ('cuda', 'cpu')
  - `BLIP_MAX_NEW_TOKENS`: Maximum number of tokens to generate
  - `BLIP_LIGHTWEIGHT`: Whether to use a lightweight model variant
  - `BLIP_LIGHTWEIGHT_MODEL`: Name of the lightweight model to use

- **Mistral/Ollama LLM settings:**
  - `LLM_MODEL_NAME`: Name of the Mistral model variant to use
  - `OLLAMA_ENDPOINT`: Endpoint for Ollama API
  - `LLM_MAX_TOKENS`: Maximum number of tokens to generate
  - `LLM_TEMPERATURE`: Temperature for generation (higher = more creative)
  - `LLM_SYSTEM_PROMPT`: System prompt to guide the LLM
  - `LLM_LIGHTWEIGHT_MODEL`: Name of the lightweight model to use
  - `LLM_PROMPT_TEMPLATE`: Template for the LLM analysis prompt (with {caption} and {affected_percentage} placeholders)

- **Development mode settings:**
  - `DEV_MODE`: Whether to run in development mode (automatic lightweight models) 
  - `USE_CUDA`: Whether to use CUDA for hardware acceleration

### Environment Variables

Configuration is managed through environment variables. Create a `.env` file in the project root with your settings:

```
# Application settings
SECRET_KEY=your-secret-key-here
DEV_MODE=true  # Set to false in production

# Hardware settings
USE_CUDA=false  # Set to true if GPU is available

# UNet/TorchServe settings
UNET_MODEL_ENDPOINT=http://localhost:8080/predictions/unet-plants

# BLIP-2 settings
BLIP_MODEL_NAME=Salesforce/blip2-opt-2.7b
BLIP_DEVICE=cpu  # cpu or cuda
BLIP_MAX_NEW_TOKENS=50
BLIP_LIGHTWEIGHT=true  # Set to true for development
BLIP_LIGHTWEIGHT_MODEL=Salesforce/blip-image-captioning-base

# Mistral/Ollama LLM settings
LLM_MODEL_NAME=mistral
OLLAMA_ENDPOINT=http://localhost:11434/api/generate
LLM_MAX_TOKENS=1000
LLM_TEMPERATURE=0.7
LLM_LIGHTWEIGHT_MODEL=mistral:7b-instruct-v0.2-q4_0
LLM_PROMPT_TEMPLATE="Image Caption: {caption}\n\nAffected Area: Approximately {affected_percentage:.1f}% of the plant shows signs of stress or damage.\n\nBased on this information, please provide:\n1. A diagnosis of the most likely issues affecting this plant\n2. Potential causes of these symptoms\n3. Recommended treatments or interventions\n4. Preventative measures for the future"
```

## Usage

(Other sections of the README remain unchanged) 