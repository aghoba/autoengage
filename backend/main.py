# main.py: bring it all together
from fastapi import FastAPI
from backend.routers import auth, page, webhook
from fastapi.middleware.cors import CORSMiddleware
from backend.config   import JWKS_URL, FRONTEND_API, ALLOWED_ORIGIN

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(page.router)
app.include_router(webhook.router)
