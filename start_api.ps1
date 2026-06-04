# Start the sf-agents API server with reload scoped to source directories only.
# This prevents trace_logs/ and audit_logs/ from triggering hot-reloads.
uvicorn api.main:app `
    --reload `
    --reload-dir api `
    --reload-dir src `
    --port 8000
