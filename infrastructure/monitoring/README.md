# Monitoring

* Logs: JSON to stdout (`LOG_JSON=true`) with `request_id` and `tenant_id` on every line.
* Health: `/api/v1/health` (liveness), `/api/v1/ready` (dependency readiness incl. worker heartbeat).
* Phase 13: Langfuse/LangSmith traces per LangGraph run; latency, token and cost metrics per stage.
