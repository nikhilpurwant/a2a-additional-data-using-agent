import os
import jwt
import json
import logging
from contextvars import ContextVar
from typing import Any
import firebase_admin
from firebase_admin import firestore

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.models import LlmResponse
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.genai import types

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Firebase Admin SDK
firebase_project_id = os.environ.get("FIREBASE_PROJECT_ID")
if firebase_project_id:
    firebase_admin.initialize_app(options={'projectId': firebase_project_id})
else:
    firebase_admin.initialize_app()

db = firestore.client()

# ContextVar to hold all decoded claims
a2a_claims_var: ContextVar[dict | None] = ContextVar("a2a_claims", default=None)
a2a_headers_var: ContextVar[dict | None] = ContextVar("a2a_headers", default=None)

async def dump_claims_callback(callback_context, llm_request) -> LlmResponse | None:
    """Bypasses LLM model call and returns safe headers and multi-claims dump."""
    claims_data = a2a_claims_var.get() or {}
    headers = a2a_headers_var.get() or {}
    
    safe_headers = {}
    for k, v in headers.items():
        if k.lower() in ["authorization", "x-serverless-authorization"]:
            safe_headers[k] = "[REDACTED_BEARER_TOKEN]"
        else:
            safe_headers[k] = v

    # Firestore Lookup
    sub_or_aud_based = os.environ.get("SUB_OR_AUD_BASED", "sub").lower()
    auth_claims = claims_data.get('authorization') or {}
    
    search_value = None
    field_name = None
    
    if sub_or_aud_based == "sub":
        search_value = auth_claims.get("sub")
        field_name = "sub"
    elif sub_or_aud_based == "aud":
        search_value = auth_claims.get("aud")
        field_name = "azp_or_aud" # Based on sample document
        
    api_key_response = ""
    if search_value:
        try:
            users_ref = db.collection("users")
            query = users_ref.where(field_name, "==", search_value).limit(1)
            docs = query.stream()
            
            found_doc = None
            for doc in docs:
                found_doc = doc.to_dict()
                break
                
            if found_doc:
                api_key_response = f"I found data for {sub_or_aud_based} ({search_value}):\n```json\n{json.dumps(found_doc, indent=2)}\n```"
            else:
                default_msg = f"Did not find data for {sub_or_aud_based} ({search_value})."
                api_key_response = os.environ.get("DATA_NOT_FOUND_MESSAGE", default_msg)
        except Exception as e:
            logging.error(f"Firestore query failed: {e}")
            api_key_response = f"Error accessing Firestore: {e}"
    else:
        api_key_response = f"Could not extract {sub_or_aud_based} claim from token."

    response_text = (
        f"📢 {api_key_response}\n\n"
        "🔍 Inspection Results:\n\n"
        "### Incoming Safe Headers\n"
        f"```json\n{json.dumps(safe_headers, indent=2)}\n```\n\n"
        "### Decoded Authorization Claims\n"
        f"```json\n{json.dumps(claims_data.get('authorization') or {}, indent=2)}\n```\n\n"
        "### Decoded X-Serverless-Authorization Claims\n"
        f"```json\n{json.dumps(claims_data.get('x-serverless-authorization') or {}, indent=2)}\n```\n\n"
    )

    logging.info("Dump claims callback triggered, bypassing LLM call.")
    
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(text=response_text)]
        )
    )


root_agent = LlmAgent(
    model=os.environ.get("GOOGLE_MODEL", "gemini-2.5-flash"),
    name="sub_client_grabber_agent",
    description="Utility agent that dumps the callers JWT claims back to them.",
    instruction="Dump JWT claims.",
    before_model_callback=dump_claims_callback,
    tools=[] # Toolless
)

from a2a.types import AgentCard

# Serve via A2A
# this port is used to create the Agent url in the card. as such the server runs on whatver we are running uvicorn on
port = int(os.environ.get("A2A_GRABBER_PORT", "8001")) 

# Build dynamic card honoring Cloud Run assignments
card_url = os.environ.get("AGENT_URL", f"http://localhost:{port}")

agent_card_data = {
  "capabilities": {},
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "description": "Utility agent that dumps the callers JWT claims back to them.",
  "name": "sub_client_grabber_agent",
  "preferredTransport": "JSONRPC",
  "protocolVersion": "0.3.0",
  "skills": [
    {
      "description": "Utility agent that dumps the callers JWT claims back to them. Dump JWT claims.",
      "examples": [],
      "id": "sub_client_grabber_agent",
      "name": "model",
      "tags": ["llm"]
    }
  ],
  "supportsAuthenticatedExtendedCard": "false",
  "url": card_url,
  "version": "0.0.1"
}

a2a_app = to_a2a(root_agent, port=port, agent_card=AgentCard(**agent_card_data))

# Add Starlette middleware to intercept the Bearer token
@a2a_app.middleware("http")
async def jwt_interceptor_middleware(request, call_next):
    # Parse standard Authorization
    claims_auth = {}
    auth_header = request.headers.get("Authorization")
    if auth_header:
        if auth_header.lower().startswith("bearer "):
            try:
                # Split at most once to separate prefix from token
                token = auth_header.split(None, 1)[1]
                
                # Check if it is a Google Opaque Access Token (ya29.)
                if token.startswith("ya29."):
                    import httpx
                    async with httpx.AsyncClient() as client:
                        # 1. Fetch identity claims (email, profile, etc.) from userinfo endpoint
                        resp_user = await client.get(
                            "https://www.googleapis.com/oauth2/v3/userinfo",
                            headers={"Authorization": f"Bearer {token}"}
                        )
                        
                        # 2. Fetch token authorization context (aud, scopes, expiry) from tokeninfo endpoint
                        resp_token = await client.get(
                            f"https://oauth2.googleapis.com/tokeninfo?access_token={token}"
                        )
                        
                        claims_auth = {}
                        
                        # Merge valid collections of claims together
                        if resp_user.status_code == 200:
                            claims_auth.update(resp_user.json())
                            
                        if resp_token.status_code == 200:
                            claims_auth.update(resp_token.json())
                            
                        # If logic was unable to formulate valid claims from either endpoint, report the errors
                        if not claims_auth:
                            claims_auth = {
                                "error": f"Google resolution failed. UserInfo status: {resp_user.status_code}, TokenInfo status: {resp_token.status_code}"
                            }
                else:
                    # Fallback to local JWT decode
                    claims_auth = jwt.decode(token, options={"verify_signature": False})
            except Exception as e:
                token_head = token[:15] if token else ""
                claims_auth = {"error": f"Resolution failed: {e}. Token head: {token_head}..."}
        else:
            claims_auth = {"error": f"Absent 'Bearer ' prefix. Value head: {auth_header[:25]}..."}

    # Parse Cloud Run Serverless Authorization
    claims_serv = {}
    serv_header = request.headers.get("x-serverless-authorization")
    if serv_header:
        if serv_header.lower().startswith("bearer "):
            try:
                token = serv_header.split(None, 1)[1]
                claims_serv = jwt.decode(token, options={"verify_signature": False})
            except Exception as e:
                claims_serv = {"error": f"JWT decode failed: {e}"}
        else:
            claims_serv = {"error": f"Absent 'Bearer ' prefix. Value head: {serv_header[:25]}..."}

    claims_data = {
        "authorization": claims_auth,
        "x-serverless-authorization": claims_serv
    }
            
    # Set context vars
    token_st = a2a_claims_var.set(claims_data)
    headers_st = a2a_headers_var.set(dict(request.headers))
    try:
        response = await call_next(request)
        return response
    finally:
        a2a_claims_var.reset(token_st)
        a2a_headers_var.reset(headers_st)
