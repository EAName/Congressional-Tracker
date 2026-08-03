-- Deprecated standalone file: dim_legislator DDL now lives in sql/schema.sql.
-- Kept so older apply_sql_file('ddl_dim_legislator.sql') callers still work.

CREATE TABLE IF NOT EXISTS dim_legislator (
    bioguide_id       TEXT NOT NULL,
    govtrack_id       INTEGER,
    icpsr_id          INTEGER,
    lis_member_id     TEXT,
    full_name         TEXT NOT NULL,
    chamber           TEXT NOT NULL CHECK (chamber IN ('House', 'Senate')),
    state             TEXT NOT NULL CHECK (state = 'VA'),
    district_current  INTEGER,
    party             TEXT,
    term_start        DATE NOT NULL,
    term_end          DATE NOT NULL,
    first_elected     INTEGER NOT NULL,
    is_incumbent      BOOLEAN NOT NULL,
    website           TEXT,
    PRIMARY KEY (bioguide_id, term_start)
);
