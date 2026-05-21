import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'vekas-construction-secret-change-in-production')

    # MySQL connection. Set secrets in environment variables.
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'Dhanush@12')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'vekas_construction')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', 3306))

    # File uploads
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
    ALLOWED_EXTENSIONS = {
        'pdf', 'dwg', 'dxf', 'rvt', 'skp',
        'xlsx', 'xls', 'csv',
        'doc', 'docx', 'txt',
        'png', 'jpg', 'jpeg', 'gif', 'webp',
        'mp4', 'avi', 'mov',
        'zip', 'rar', '7z',
        'ifc', 'nwd',
    }
    PROJECT_STORAGE_LIMIT = 1 * 1024 * 1024 * 1024

    # Anthropic AI. Set this in the environment when needed.
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
