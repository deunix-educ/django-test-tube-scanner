from .celerymodule import appc as celery_app

__all__ = ('celery_app',)
__version__ = "0.1"

default_app_config = 'home.apps.HomeConfig'