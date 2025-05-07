import os
from dotenv import load_dotenv
import httpx

from fastapi import FastAPI, Depends, HTTPException
from clerk_backend_api import Clerk
from clerk_backend_api.jwks_helpers import authenticate_request, AuthenticateRequestOptions
import asyncpg

# Load .env into os.environ
load_dotenv()

# Configuration
DATABASE_URL  = os.getenv("DATABASE_URL")
CLERK_API_KEY = os.getenv("CLERK_API_KEY")

# Initialize Clerk client
clerk = Clerk(bearer_auth=CLERK_API_KEY)

# FastAPI app
app = FastAPI()

async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.close()

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/auth/callback")
async def auth_callback(token: str, db=Depends(get_db)):
    """
    Verify the Clerk session token, then upsert a tenant record.
    Frontend should POST the Clerk session token here.
    """
    # Construct a fake request object so authenticate_request can run
    fake_req = httpx.Request(
        "GET",
        "http://localhost/auth",
        headers={"Authorization": f"Bearer {token}"}
    )

    # Validate the JWT and fetch payload
    auth_state = clerk.authenticate_request(
        fake_req,
        AuthenticateRequestOptions(
            # Optionally constrain which frontends/origins can call this
            authorized_parties=["https://your-frontend.example.com"]
        )
    )
    if not auth_state.is_signed_in:
        raise HTTPException(status_code=401, detail="Invalid Clerk session token")

    # Extract the Clerk user ID from the verified token
    user_id = auth_state.payload["sub"]

    # Upsert into tenants table
    await db.execute(
        """
        INSERT INTO tenants (user_id)
        VALUES ($1)
        ON CONFLICT (user_id) DO NOTHING
        """,
        user_id
    )

    return {"user_id": user_id}
