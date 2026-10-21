web: uvicorn freight_agent.api.app:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m freight_agent.workers.timer_worker
