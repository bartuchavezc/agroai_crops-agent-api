"""
Application entry point.
"""
import uvicorn
import os
from dotenv import load_dotenv

from src import create_app, container

# Load environment variables
load_dotenv()

# Create the FastAPI app instance, passing the configured container
app = create_app(app_container=container)

if __name__ == "__main__":
    # Get host and port from environment variables or use defaults
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 80))
    
    # Run the Uvicorn server
    uvicorn.run(app, host=host, port=port) 