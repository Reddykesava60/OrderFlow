import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dineflow.settings.prod')

app = Celery('dineflow')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

import logging
from celery.signals import task_prerun, task_postrun, task_failure

logger = logging.getLogger(__name__)

@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    logger.info("task_started task=%s task_id=%s", task.name, task_id)

@task_postrun.connect
def task_postrun_handler(task_id, task, *args, retval=None, state=None, **kwargs):
    logger.info("task_completed task=%s task_id=%s state=%s", task.name, task_id, state)

@task_failure.connect
def task_failure_handler(task_id, exception, traceback, einfo, args, kwargs, **kw):
    # Using task_id directly, kw.get('sender') has the task name sometimes
    task_name = kw.get('sender').name if hasattr(kw.get('sender'), 'name') else 'unknown'
    logger.error("task_failed task=%s task_id=%s error=%s", task_name, task_id, str(exception))
