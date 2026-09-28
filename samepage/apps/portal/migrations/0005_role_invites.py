"""Role invites: an existing account gets a judge or organizer role only by accepting a one-time link."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0004_lifecycle'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='invite',
            name='invite_kind',
        ),
        migrations.RemoveConstraint(
            model_name='invite',
            name='invite_target',
        ),
        migrations.AddField(
            model_name='invite',
            name='role',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='invite',
            name='tracks',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddConstraint(
            model_name='invite',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ('team', 'password', 'role'))), name='invite_kind'),
        ),
        migrations.AddConstraint(
            model_name='invite',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'team'), ('team__isnull', False)), models.Q(('kind', 'password'), ('person__isnull', False)), models.Q(('kind', 'role'), ('person__isnull', False), ('event__isnull', False), ('role__in', ('judge', 'organizer'))), _connector='OR'), name='invite_target'),
        ),
    ]
