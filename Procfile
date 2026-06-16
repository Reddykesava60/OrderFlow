web: daphne --bind 0.0.0.0 --port $PORT --access-log - --proxy-headers dineflow.asgi:application
worker: celery -A dineflow worker -Q celery,payments -l info --concurrency=2
beat: celery -A dineflow beat -l info
