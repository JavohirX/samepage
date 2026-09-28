from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION submission_deadline() RETURNS trigger AS $$
DECLARE
  close_at timestamptz;
  covered boolean;
  stamp text;
BEGIN
  SELECT submissions_close INTO close_at FROM event WHERE id = NEW.event_id;
  stamp := to_char(close_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
  IF TG_OP = 'INSERT' THEN
    IF NEW.origin = 'import' THEN
      IF NEW.submitted_at IS NOT NULL AND NEW.submitted_at > close_at THEN
        RAISE EXCEPTION 'submissions closed at %', stamp;
      END IF;
    ELSIF now() > close_at THEN
      RAISE EXCEPTION 'submissions closed at %', stamp;
    END IF;
    RETURN NEW;
  END IF;
  IF now() > close_at AND (
    NEW.title IS DISTINCT FROM OLD.title OR
    NEW.tagline IS DISTINCT FROM OLD.tagline OR
    NEW.description IS DISTINCT FROM OLD.description OR
    NEW.thumbnail IS DISTINCT FROM OLD.thumbnail OR
    NEW.video_url IS DISTINCT FROM OLD.video_url OR
    NEW.repo_url IS DISTINCT FROM OLD.repo_url OR
    NEW.live_url IS DISTINCT FROM OLD.live_url OR
    NEW.tech_tags IS DISTINCT FROM OLD.tech_tags OR
    NEW.custom_answers IS DISTINCT FROM OLD.custom_answers OR
    NEW.track_id IS DISTINCT FROM OLD.track_id
  ) THEN
    SELECT EXISTS (
      SELECT 1 FROM deadline_exception WHERE submission_id = NEW.id AND until > now()
    ) INTO covered;
    IF NOT covered THEN
      RAISE EXCEPTION 'submissions closed at %', stamp;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS submission_deadline ON submission;
CREATE TRIGGER submission_deadline
BEFORE INSERT OR UPDATE ON submission
FOR EACH ROW EXECUTE FUNCTION submission_deadline();

CREATE OR REPLACE FUNCTION append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS score_rev_append_only ON score_rev;
CREATE TRIGGER score_rev_append_only
BEFORE UPDATE OR DELETE ON score_rev
FOR EACH ROW EXECUTE FUNCTION append_only();

DROP TRIGGER IF EXISTS audit_event_append_only ON audit_event;
CREATE TRIGGER audit_event_append_only
BEFORE UPDATE OR DELETE ON audit_event
FOR EACH ROW EXECUTE FUNCTION append_only();

CREATE OR REPLACE FUNCTION score_final_guard() RETURNS trigger AS $$
DECLARE
  prev_state text;
  unlock_ok boolean;
BEGIN
  SELECT state INTO prev_state
  FROM score_rev
  WHERE judge_id = NEW.judge_id
    AND submission_id = NEW.submission_id
    AND criterion = NEW.criterion
  ORDER BY rev DESC
  LIMIT 1;
  IF prev_state = 'final' AND NEW.state IS DISTINCT FROM 'unlocked' THEN
    RAISE EXCEPTION 'score is final';
  END IF;
  IF prev_state = 'final' AND NEW.state = 'unlocked' THEN
    SELECT EXISTS (
      SELECT 1 FROM audit_event WHERE seq = NEW.audit_seq AND action = 'score.unlock'
    ) INTO unlock_ok;
    IF NOT COALESCE(unlock_ok, false) THEN
      RAISE EXCEPTION 'unlock requires a score.unlock audit event';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS score_final_guard ON score_rev;
CREATE TRIGGER score_final_guard
BEFORE INSERT ON score_rev
FOR EACH ROW EXECUTE FUNCTION score_final_guard();

CREATE OR REPLACE VIEW score_current AS
SELECT DISTINCT ON (judge_id, submission_id, criterion)
  id, judge_id, submission_id, criterion, rev, value, state, comment, audit_seq
FROM score_rev
ORDER BY judge_id, submission_id, criterion, rev DESC;
"""

REVERSE = r"""
DROP VIEW IF EXISTS score_current;
DROP TRIGGER IF EXISTS score_final_guard ON score_rev;
DROP TRIGGER IF EXISTS audit_event_append_only ON audit_event;
DROP TRIGGER IF EXISTS score_rev_append_only ON score_rev;
DROP TRIGGER IF EXISTS submission_deadline ON submission;
DROP FUNCTION IF EXISTS score_final_guard();
DROP FUNCTION IF EXISTS append_only();
DROP FUNCTION IF EXISTS submission_deadline();
"""


class Migration(migrations.Migration):
    dependencies = [("portal", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
