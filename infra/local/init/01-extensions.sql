-- Runs once, the first time the database volume is created.
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector: vector column type + similarity search
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- trigram matching, used later for hybrid search
