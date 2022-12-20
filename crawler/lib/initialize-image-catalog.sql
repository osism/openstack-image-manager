CREATE TABLE IF NOT EXISTS image_catalog (
  id integer PRIMARY KEY AUTOINCREMENT,
  name text NOT NULL,
  release_date text,
  version text,
  distribution_name text,
  distribution_release text,
  url text,
  checksum text
);
