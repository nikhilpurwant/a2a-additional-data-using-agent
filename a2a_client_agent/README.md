# 🧪 Remote A2A Agent Client created with ADK

A2A consuming ADK agent.


## How to run

Adjust the `DUMMY_SUB` in agent.py and run `uv adk web --port 8000`.

Then open `http://localhost:8000/dev-ui/` in browser and use the agent client.


Make sure you have following environment variables set

```
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=<cloud-run-project-id>
GOOGLE_CLOUD_LOCATION=<cloud-run-location>

```