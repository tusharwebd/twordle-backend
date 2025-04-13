import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
worker_class = 'gevent'
workers = 1
