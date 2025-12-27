-- 2025-12-27: Rename legacy SAG tables to canonical KG tables.
--
-- This repo historically used `sag_*` tables for Knowledge Graph storage.
-- The canonical naming is now `kg_*`.
--
-- Idempotent: will only rename if `kg_*` does not exist and `sag_*` exists.

DO $$
BEGIN
  -- Core tables
  IF to_regclass('public.kg_entities') IS NULL AND to_regclass('public.sag_entities') IS NOT NULL THEN
    ALTER TABLE public.sag_entities RENAME TO kg_entities;
  END IF;

  IF to_regclass('public.kg_source_events') IS NULL AND to_regclass('public.sag_source_events') IS NOT NULL THEN
    ALTER TABLE public.sag_source_events RENAME TO kg_source_events;
  END IF;

  IF to_regclass('public.kg_event_entities') IS NULL AND to_regclass('public.sag_event_entities') IS NOT NULL THEN
    ALTER TABLE public.sag_event_entities RENAME TO kg_event_entities;
  END IF;
END $$;

-- Note: Postgres automatically updates FK targets on table rename.
-- Constraint/index names may still contain `sag_` and can be renamed optionally.

