#
# encoding: utf-8
from django.conf import settings

def params(request):
    return {
        'APP_TITLE': settings.APP_TITLE,
        'APP_SUB_TITLE': settings.APP_SUB_TITLE,
        'self_url': request.build_absolute_uri(),
    }

