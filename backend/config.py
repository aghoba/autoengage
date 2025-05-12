# config.py: load environment
import os
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
FRONTEND_API = os.getenv("CLERK_FRONTEND_API", "")
JWKS_URL = f"https://{FRONTEND_API}/.well-known/jwks.json"
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "http://localhost:3000")

PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN")