import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
# This public fallback is ONLY for the local assessment. Production must supply a secret.
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-assessment-only-not-for-deployment')
if not DEBUG and SECRET_KEY.startswith('local-assessment'):
    raise RuntimeError('Set DJANGO_SECRET_KEY when DEBUG is disabled')
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver', 'web']
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.staticfiles',
    'silk', 'orders', 'mailqueue',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'silk.middleware.SilkyMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates',
              'APP_DIRS': True, 'OPTIONS': {'context_processors': [
                  'django.template.context_processors.request',
                  'django.contrib.auth.context_processors.auth']}}]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3',
                         'NAME': os.getenv('DATABASE_PATH', str(BASE_DIR / 'db.sqlite3')),
                         'OPTIONS': {'timeout': 30}}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'UTC'
STATIC_URL = '/static/'
SILKY_AUTHENTICATION = False  # Local profiler only; never expose publicly.
SILKY_AUTHORISATION = False
SILKY_INTERCEPT_PERCENT = 100
REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')
RATE_REDIS_URL = os.getenv('RATE_REDIS_URL', 'redis://127.0.0.1:6379/1')
RATE_NAMESPACE = os.getenv('RATE_NAMESPACE', 'assessment')
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_DEFAULT_QUEUE = RATE_NAMESPACE
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_SOFT_TIME_LIMIT = 20
CELERY_TASK_TIME_LIMIT = 30
CELERY_BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 120}
CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS = {'visibility_timeout': 120}
CELERY_VISIBILITY_TIMEOUT = 120
CELERY_RESULT_EXPIRES = 3600
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BEAT_SCHEDULE = {'recover-outbox': {
    'task': 'mailqueue.tasks.dispatch_due', 'schedule': 5.0}}
