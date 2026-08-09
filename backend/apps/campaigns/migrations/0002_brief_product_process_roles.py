from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("campaigns", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="contentbriefconceptlink",
            name="role",
            field=models.CharField(
                choices=[
                    ("PRODUCT_TYPE", "Product type"),
                    ("MANUFACTURING_PROCESS", "Manufacturing process"),
                    ("TARGET_INDUSTRY", "Target industry"),
                    ("TARGET_CUSTOMER_TYPE", "Target customer type"),
                    ("PURCHASE_INTENT", "Purchase intent"),
                    ("STANDARD", "Standard"),
                    ("APPLICATION", "Application"),
                ],
                max_length=32,
            ),
        ),
    ]
