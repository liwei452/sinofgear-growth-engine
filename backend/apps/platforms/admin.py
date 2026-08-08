from django.contrib import admin

from .models import ConnectorCredential, Platform, PlatformCapability, SocialAccount

admin.site.register([Platform, PlatformCapability, ConnectorCredential, SocialAccount])

