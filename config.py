import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-for-development-only')
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'data', 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv'}
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200MB max file size for videos
    JSON_SORT_KEYS = False
    
class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False
    
class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = False
    TESTING = True
    
class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False
    
# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
} 