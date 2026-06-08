from django.conf import settings


def app_brand(request):
    return {
        'APP_NAME': settings.APP_NAME,
        'APP_SHORT_NAME': settings.APP_SHORT_NAME,
        'APP_TAGLINE': settings.APP_TAGLINE,
    }
