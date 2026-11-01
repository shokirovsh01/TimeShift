from django.db import migrations


def hours_to_minutes(apps, schema_editor):
    BountyTask = apps.get_model('bounty', 'BountyTask')
    for task in BountyTask.objects.all():
        task.reward_minutes *= 60
        task.save(update_fields=['reward_minutes'])


def minutes_to_hours(apps, schema_editor):
    BountyTask = apps.get_model('bounty', 'BountyTask')
    for task in BountyTask.objects.all():
        task.reward_minutes = max(task.reward_minutes // 60, 1)
        task.save(update_fields=['reward_minutes'])


class Migration(migrations.Migration):

    dependencies = [
        ('bounty', '0003_alter_bountytask_reward_minutes'),
    ]

    operations = [
        migrations.RunPython(hours_to_minutes, minutes_to_hours),
    ]
