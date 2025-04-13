import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
worker_class = 'geventwebsocket.gunicorn.workers.GeventWebSocketWorker'
workers = 1
timeout = 120
