# The final legacy schema is represented in 0002. Original source files were absent.
# Keep this already-applied migration identity without repeating historical DDL.
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [("usuarios", "0002_alter_user_managers_cliente")]
    operations = []
