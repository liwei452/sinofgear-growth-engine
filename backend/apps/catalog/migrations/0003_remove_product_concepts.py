from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0002_alter_product_options_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="product",
            name="concepts",
        ),
    ]
