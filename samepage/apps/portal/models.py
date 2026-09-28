"""Tables. Business rules that must survive an app bug also live in triggers."""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone


class PersonManager(BaseUserManager):
    def create_user(self, email, id=None, password=None, **extra):
        import secrets

        person = self.model(id=id or "per_" + secrets.token_hex(5), email=self.normalize_email(email).lower(), **extra)
        if password:
            person.set_password(password)
        else:
            person.set_unusable_password()
        person.save(using=self._db)
        return person

    def create_superuser(self, email, password=None, **extra):
        """`manage.py createsuperuser` and `manage.py samepage_admin` both end here: a global admin."""
        extra["is_admin"] = True
        return self.create_user(email, password=password, **extra)


class Person(AbstractBaseUser):
    id = models.TextField(primary_key=True)
    email = models.EmailField(unique=True)
    name = models.TextField(blank=True, default="")
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = PersonManager()

    class Meta:
        db_table = "person"

    def __str__(self):
        return self.email

    @property
    def is_staff(self):
        return False

    def has_perm(self, perm, obj=None):
        return bool(self.is_admin)

    def has_module_perms(self, app_label):
        return bool(self.is_admin)


class ApiToken(models.Model):
    id = models.TextField(primary_key=True)
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="tokens")
    kind = models.TextField(default="bearer")
    token_sha256 = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    demo = models.BooleanField(default=False)

    class Meta:
        db_table = "api_token"


class Event(models.Model):
    STATES = ("draft", "open", "closed", "judging", "published", "archived")
    id = models.TextField(primary_key=True)
    name = models.TextField()
    state = models.TextField(default="draft")
    submissions_close = models.DateTimeField()
    windows = models.JSONField(default=dict, blank=True)
    blind_judging = models.BooleanField(default=False)
    custom_questions = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True, default="")
    starts_at = models.DateTimeField(null=True, blank=True)
    judging_ends = models.DateTimeField(null=True, blank=True)
    max_team_size = models.PositiveSmallIntegerField(default=4)
    created_by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "event"
        constraints = [
            models.CheckConstraint(
                condition=Q(state__in=("draft", "open", "closed", "judging", "published", "archived")),
                name="event_state",
            ),
        ]


class Track(models.Model):
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tracks")
    name = models.TextField()

    class Meta:
        db_table = "track"


class PrizeCategory(models.Model):
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="prizes")
    name = models.TextField()
    track = models.ForeignKey(Track, null=True, blank=True, on_delete=models.PROTECT)
    description = models.TextField(blank=True, default="")

    class Meta:
        db_table = "prize_category"


class Criterion(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="criteria")
    track = models.ForeignKey(Track, null=True, blank=True, on_delete=models.CASCADE)
    key = models.TextField()
    label = models.TextField(blank=True, default="")
    weight = models.DecimalField(max_digits=8, decimal_places=4)
    scale_min = models.PositiveSmallIntegerField(default=1)
    scale_max = models.PositiveSmallIntegerField(default=5)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "criterion"
        constraints = [
            models.UniqueConstraint(fields=["event", "track", "key"], name="criterion_key", nulls_distinct=False),
            models.CheckConstraint(condition=Q(weight__gt=0), name="criterion_weight_positive"),
        ]


class RoleGrant(models.Model):
    ROLES = ("participant", "judge", "organizer")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="grants")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="grants")
    role = models.TextField()

    class Meta:
        db_table = "role_grant"
        constraints = [
            models.UniqueConstraint(fields=["person", "event", "role"], name="role_grant_uniq"),
            models.CheckConstraint(condition=Q(role__in=("participant", "judge", "organizer")), name="role_grant_role"),
        ]


class JudgeTrack(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="judge_tracks")
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    track = models.ForeignKey(Track, on_delete=models.CASCADE)

    class Meta:
        db_table = "judge_track"
        constraints = [
            models.UniqueConstraint(fields=["person", "track"], name="judge_track_uniq"),
        ]


class Team(models.Model):
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="teams")
    name = models.TextField()

    class Meta:
        db_table = "team"


class TeamMember(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="memberships")

    class Meta:
        db_table = "team_member"
        constraints = [
            models.UniqueConstraint(fields=["event", "person"], name="one_team_per_event"),
        ]


class Invite(models.Model):
    """A secret link. `team`: joins a team. `password`: sets the password of an account an organizer created.

    Only the sha256 of the token is stored. The link is shown once, to the person who made it.
    """

    KINDS = ("team", "password")
    id = models.TextField(primary_key=True)
    kind = models.TextField(default="team")
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE, related_name="invites")
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.CASCADE, related_name="invites")
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE, related_name="password_invites")
    token_sha256 = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(default=1)
    uses = models.PositiveIntegerField(default=0)
    created_by = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "invite"
        constraints = [
            models.CheckConstraint(condition=Q(uses__lte=models.F("max_uses")), name="invite_uses_cap"),
            models.CheckConstraint(condition=Q(kind__in=("team", "password")), name="invite_kind"),
            models.CheckConstraint(
                condition=(Q(kind="team") & Q(team__isnull=False)) | (Q(kind="password") & Q(person__isnull=False)),
                name="invite_target",
            ),
        ]


class Submission(models.Model):
    STATES = ("draft", "submitted", "locked", "withdrawn")
    ORIGINS = ("native", "import")
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="submissions")
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="submissions")
    track = models.ForeignKey(Track, on_delete=models.PROTECT, related_name="submissions")
    position = models.PositiveIntegerField(default=0)
    title = models.TextField(blank=True, default="")
    tagline = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    thumbnail = models.TextField(blank=True, default="")
    video_url = models.TextField(blank=True, default="")
    repo_url = models.TextField(blank=True, default="")
    live_url = models.TextField(blank=True, default="")
    tech_tags = ArrayField(models.TextField(), default=list, blank=True)
    custom_answers = models.JSONField(default=dict, blank=True)
    state = models.TextField(default="draft")
    origin = models.TextField(default="native")
    submitted_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    duplicate_group = models.ForeignKey(
        "DuplicateGroup", null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions"
    )
    withdrawn_reason = models.TextField(blank=True, default="")
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_from"
    )

    class Meta:
        db_table = "submission"
        constraints = [
            models.CheckConstraint(condition=Q(state__in=("draft", "submitted", "locked", "withdrawn")), name="submission_state"),
            models.CheckConstraint(condition=Q(origin__in=("native", "import")), name="submission_origin"),
            models.UniqueConstraint(
                fields=["event", "team"],
                condition=Q(origin="native") & ~Q(state="withdrawn"),
                name="submission_one_active_native",
            ),
        ]


class SubmissionMedia(models.Model):
    KINDS = ("thumbnail", "gallery")
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="media")
    kind = models.TextField()
    position = models.PositiveSmallIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    content_type = models.TextField()
    path = models.TextField(blank=True, default="")
    # Image bytes live in Postgres, so a pg_dump is the whole backup and the app needs no writable disk.
    data = models.BinaryField(default=b"")
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "submission_media"
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=("thumbnail", "gallery")), name="media_kind"),
            models.CheckConstraint(condition=Q(position__lte=6), name="media_position_cap"),
        ]


class DeadlineException(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="exceptions")
    until = models.DateTimeField()
    granted_by = models.TextField()
    audit_seq = models.BigIntegerField()

    class Meta:
        db_table = "deadline_exception"


class Coi(models.Model):
    judge = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="conflicts")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="conflicts")
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "coi"
        constraints = [
            models.UniqueConstraint(fields=["judge", "team"], name="coi_uniq"),
        ]


class DuplicateGroup(models.Model):
    RESOLUTIONS = ("keep_latest", "merge")
    STATUSES = ("provisional", "confirmed")
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="duplicates")
    rule = models.TextField()
    members = ArrayField(models.TextField(), default=list)
    resolution = models.TextField(default="keep_latest")
    status = models.TextField(default="provisional")
    resolved_by = models.TextField(blank=True, default="")
    audit_seq = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "duplicate_group"
        constraints = [
            models.CheckConstraint(condition=Q(resolution__in=("keep_latest", "merge")), name="dup_resolution"),
            models.CheckConstraint(condition=Q(status__in=("provisional", "confirmed")), name="dup_status"),
        ]


class AssignmentRun(models.Model):
    KINDS = ("import", "initial", "topup", "dry_run", "manual")
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="assignment_runs")
    kind = models.TextField()
    seed = models.BigIntegerField(default=1)
    params = models.JSONField(default=dict)
    report = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "assignment_run"


class Batch(models.Model):
    STATES = ("issued", "in_progress", "done", "abandoned")
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="batches")
    judge = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="batches")
    run = models.ForeignKey(AssignmentRun, on_delete=models.CASCADE, related_name="batches")
    state = models.TextField(default="issued")

    class Meta:
        db_table = "batch"
        constraints = [
            models.CheckConstraint(condition=Q(state__in=("issued", "in_progress", "done", "abandoned")), name="batch_state"),
        ]


class Assignment(models.Model):
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="assignments")
    judge = models.ForeignKey(Person, on_delete=models.PROTECT)
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="assignments")
    source = models.TextField(default="import")
    opened_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "assignment"
        constraints = [
            models.UniqueConstraint(fields=["judge", "submission"], name="assignment_once"),
        ]


class ScoreRev(models.Model):
    STATES = ("draft", "final", "unlocked")
    judge = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="score_revs")
    submission = models.ForeignKey(Submission, on_delete=models.PROTECT, related_name="score_revs")
    criterion = models.TextField()
    rev = models.PositiveIntegerField()
    value = models.PositiveSmallIntegerField()
    state = models.TextField()
    comment = models.TextField(blank=True, default="")
    audit_seq = models.BigIntegerField()

    class Meta:
        db_table = "score_rev"
        constraints = [
            models.UniqueConstraint(
                fields=["judge", "submission", "criterion", "rev"],
                name="score_rev_uniq",
            ),
            models.CheckConstraint(condition=Q(value__gte=1, value__lte=5), name="score_value_scale"),
            models.CheckConstraint(condition=Q(state__in=("draft", "final", "unlocked")), name="score_state"),
        ]


class ScoreCurrent(models.Model):
    """Unmanaged mirror of the score_current view. Created in migration 0002."""

    judge = models.ForeignKey(Person, on_delete=models.DO_NOTHING, related_name="+")
    submission = models.ForeignKey(Submission, on_delete=models.DO_NOTHING, related_name="+")
    criterion = models.TextField()
    rev = models.PositiveIntegerField()
    value = models.PositiveSmallIntegerField()
    state = models.TextField()
    comment = models.TextField()
    audit_seq = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "score_current"


class AuditEvent(models.Model):
    seq = models.BigAutoField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="audit_events")
    actor = models.TextField()
    action = models.TextField()
    object_ref = models.TextField(db_column="object")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    at = models.DateTimeField(default=timezone.now)
    prev_hash = models.TextField()
    hash = models.TextField()

    class Meta:
        db_table = "audit_event"
        ordering = ["seq"]


class ResultsSnapshot(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="snapshots")
    seq = models.PositiveIntegerField()
    method = models.TextField()
    ranking_sha256 = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict)
    cause_audit_seq = models.BigIntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    seconds = models.FloatField(default=0)
    # sha256 of the fit's inputs (counted reviews, weights, active projects). A mismatch means stale.
    input_fingerprint = models.TextField(blank=True, default="")

    class Meta:
        db_table = "results_snapshot"
        constraints = [
            models.UniqueConstraint(fields=["event", "seq"], name="snapshot_seq"),
        ]


class NormalizationRun(models.Model):
    id = models.TextField(primary_key=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="normalization_runs")
    method = models.TextField()
    params = models.JSONField(default=dict)
    input_sha256 = models.TextField(blank=True, default="")
    output = models.JSONField(default=dict)
    state = models.TextField(default="ok")
    seconds = models.FloatField(default=0)

    class Meta:
        db_table = "normalization_run"
        constraints = [
            models.CheckConstraint(condition=Q(state__in=("ok", "failed")), name="norm_state"),
        ]
