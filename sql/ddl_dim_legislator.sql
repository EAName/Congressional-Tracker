-- dim_legislator: Virginia SCD2 dimension for the 119th Congress.
-- Natural key: (bioguide_id, term_start). lis_id retained for Senate roll-call
-- crosswalk (Prompt 3); bioguide_id remains the sole join key elsewhere.

CREATE TABLE IF NOT EXISTS dim_legislator (
    bioguide_id       TEXT NOT NULL,
    govtrack_id       INTEGER,
    icpsr_id          INTEGER,
    lis_id            TEXT,
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
