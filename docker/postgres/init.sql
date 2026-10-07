-- Runs once, on first start of an empty data volume.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE DATABASE slotline_test;
\connect slotline_test
CREATE EXTENSION IF NOT EXISTS btree_gist;
