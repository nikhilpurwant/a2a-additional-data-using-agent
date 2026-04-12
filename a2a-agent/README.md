# 🕵️‍♂️ A2A ADK Agent for header inspection and firebase data retrieval

This agent reads Auth header and extracts the sub from it. It then queries firebase to get the data associated with the sub.

## 🚀 Running Locally

Ensure workspace top-level installation mounted dependencies:

```bash
uv run pip install -r requirements.txt
uv run uvicorn agent:a2a_app --port 8001
```

Test it using `a2a_client_agent`

## ☁️ Deployment (Cloud Run)

A supportive `Dockerfile` is provided for containerized packaging and deployment.

Make sure you have following environment variables set

```
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=<cloud-run-project-id>
GOOGLE_CLOUD_LOCATION=<cloud-run-location>
SUB_OR_AUD_BASED=sub
FIREBASE_PROJECT_ID=<firebase-project-id>
DATA_NOT_FOUND_MESSAGE="Please login and add data to <firebase-app-url>"


```

Also wherever you run this agent, `roles/datastore.viewer` permission must be provided to the service account


```bash
   
   # Example for the agent runnning as a cloud run service with default compute service account
   
   gcloud projects add-iam-policy-binding <your-firebase-project-id> \
    --member="serviceAccount:OTHER_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/datastore.viewer"

```

