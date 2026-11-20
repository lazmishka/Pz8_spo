from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticket",
            name="status",
            field=models.CharField(
                choices=[("new", "Новая"), ("progress", "В работе"), ("done", "Выполнена")],
                default="new",
                max_length=8,
            ),
        ),
    ]
