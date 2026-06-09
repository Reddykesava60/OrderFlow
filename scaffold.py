import os

apps = ['identity', 'operations', 'catalog', 'customers', 'sales', 'payments', 'finance', 'kitchen', 'admin_portal']

for app in apps:
    path = f'apps/{app}/apps.py'
    content = f'''from django.apps import AppConfig

class {app.title().replace("_", "")}Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.{app}"
'''
    with open(path, 'w') as f:
        f.write(content)

print("Scaffolded apps.py")
