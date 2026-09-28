"""Event lifecycle columns, team and password invites, image bytes in Postgres, snapshot fingerprints.

The media trigger is the database copy of the deadline for images: after the event's close
an image can be neither added nor removed, whatever the application does.
"""

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

MEDIA_DEADLINE = r"""
CREATE OR REPLACE FUNCTION submission_media_deadline() RETURNS trigger AS $$
DECLARE
  close_at timestamptz;
  target text;
  covered boolean;
BEGIN
  IF TG_OP = 'DELETE' THEN
    target := OLD.submission_id;
  ELSE
    target := NEW.submission_id;
  END IF;
  SELECT e.submissions_close INTO close_at
  FROM submission s JOIN event e ON e.id = s.event_id
  WHERE s.id = target;
  IF close_at IS NOT NULL AND now() > close_at THEN
    SELECT EXISTS (
      SELECT 1 FROM deadline_exception WHERE submission_id = target AND until > now()
    ) INTO covered;
    IF NOT covered THEN
      RAISE EXCEPTION 'submissions closed at %', to_char(close_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS submission_media_deadline ON submission_media;
CREATE TRIGGER submission_media_deadline
BEFORE INSERT OR UPDATE OR DELETE ON submission_media
FOR EACH ROW EXECUTE FUNCTION submission_media_deadline();
"""

MEDIA_DEADLINE_REVERSE = r"""
DROP TRIGGER IF EXISTS submission_media_deadline ON submission_media;
DROP FUNCTION IF EXISTS submission_media_deadline();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('portal', '0003_throttle_cache'),
    ]

    operations = [
        migrations.AddField(
            model_name='criterion',
            name='label',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='event',
            name='created_by',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='event',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='event',
            name='judging_ends',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='event',
            name='max_team_size',
            field=models.PositiveSmallIntegerField(default=4),
        ),
        migrations.AddField(
            model_name='event',
            name='starts_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='invite',
            name='created_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='invite',
            name='created_by',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='invite',
            name='event',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='invites', to='portal.event'),
        ),
        migrations.AddField(
            model_name='invite',
            name='kind',
            field=models.TextField(default='team'),
        ),
        migrations.AddField(
            model_name='invite',
            name='person',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='password_invites', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='prizecategory',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='resultssnapshot',
            name='input_fingerprint',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='submissionmedia',
            name='created_at',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name='submissionmedia',
            name='data',
            field=models.BinaryField(default=b''),
        ),
        migrations.AddField(
            model_name='submissionmedia',
            name='size',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='invite',
            name='team',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='invites', to='portal.team'),
        ),
        migrations.AlterField(
            model_name='submissionmedia',
            name='path',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddConstraint(
            model_name='invite',
            constraint=models.CheckConstraint(condition=models.Q(('kind__in', ('team', 'password'))), name='invite_kind'),
        ),
        migrations.AddConstraint(
            model_name='invite',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('kind', 'team'), ('team__isnull', False)), models.Q(('kind', 'password'), ('person__isnull', False)), _connector='OR'), name='invite_target'),
        ),
        migrations.RunSQL(MEDIA_DEADLINE, MEDIA_DEADLINE_REVERSE),
    ]
