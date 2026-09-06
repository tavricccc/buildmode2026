-- Social-work notes are user-entered case records, separate from model output.
CREATE TABLE IF NOT EXISTS social_work_records (
  record_id       TEXT PRIMARY KEY,
  subject_id      TEXT NOT NULL,
  record_type     TEXT NOT NULL CHECK(record_type IN ('visit','phone','case_note','follow_up','resource_referral')),
  occurred_at_ms  INTEGER NOT NULL,
  author          TEXT NOT NULL DEFAULT '',
  content         TEXT NOT NULL,
  tags_json       TEXT NOT NULL DEFAULT '[]',
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_social_work_subject_time
  ON social_work_records(subject_id, occurred_at_ms DESC);

-- Generated reports retain their source ids so they remain auditable.
CREATE TABLE IF NOT EXISTS status_reports (
  report_id       TEXT PRIMARY KEY,
  subject_id      TEXT NOT NULL,
  report_type     TEXT NOT NULL CHECK(report_type IN ('daily_status','follow_up','case_summary')),
  window_start_ms INTEGER NOT NULL,
  window_end_ms   INTEGER NOT NULL,
  title           TEXT NOT NULL,
  body            TEXT NOT NULL,
  sources_json    TEXT NOT NULL DEFAULT '{}',
  created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status_reports_subject_time
  ON status_reports(subject_id, window_end_ms DESC);
