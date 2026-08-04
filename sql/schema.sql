-- Star schema for VA Congressional Tracker (DuckDB).
-- Natural keys only; MERGE loads upsert on these PKs.

CREATE TABLE IF NOT EXISTS dim_legislator (
    bioguide_id       TEXT NOT NULL,
    govtrack_id       INTEGER,
    icpsr_id          INTEGER,
    lis_member_id     TEXT,
    full_name         TEXT NOT NULL,
    chamber           TEXT NOT NULL CHECK (chamber IN ('House', 'Senate')),
    state             TEXT NOT NULL CHECK (state = 'VA'),
    district_current  INTEGER,
    district_2025     INTEGER,   -- district under the 2021 court-drawn map
    district_2026     INTEGER,   -- district under the 2026 proposed map (numbering persists)
    party             TEXT,
    term_start        DATE NOT NULL,
    term_end          DATE NOT NULL,
    first_elected     INTEGER NOT NULL,
    is_incumbent      BOOLEAN NOT NULL,
    website           TEXT,
    PRIMARY KEY (bioguide_id, term_start)
);

-- Geography differs by map_version even when district_number is unchanged.
-- Every analytic/export MUST declare which map_version it is keyed to.
CREATE TABLE IF NOT EXISTS dim_district (
    district_number    INTEGER NOT NULL,
    map_version        TEXT NOT NULL CHECK (map_version IN ('2021', '2026')),
    incumbent_bioguide TEXT,
    partisan_lean      TEXT,
    is_target          BOOLEAN NOT NULL,
    PRIMARY KEY (district_number, map_version)
);

CREATE TABLE IF NOT EXISTS dim_bill (
    bill_id                  TEXT PRIMARY KEY,  -- hr-2966-119
    congress                 INTEGER NOT NULL,
    bill_type                TEXT NOT NULL,      -- hr, s, hres, sres, hjres, sjres, pn
    bill_number              INTEGER,            -- NULL for some PN forms
    bill_number_raw          TEXT,               -- preserve PN forms like 11-18
    title                    TEXT,
    short_title              TEXT,
    plain_language_summary   TEXT,               -- human-written, under 25 words
    sponsor_bioguide         TEXT,
    introduced_date          DATE,
    policy_area              TEXT
);

CREATE TABLE IF NOT EXISTS fact_vote (
    vote_id         TEXT PRIMARY KEY,  -- h-119-1-156 / s-119-2-380
    congress        INTEGER NOT NULL,
    session         INTEGER NOT NULL,
    chamber         TEXT NOT NULL CHECK (chamber IN ('House', 'Senate')),
    roll_number     INTEGER NOT NULL,
    vote_date       DATE NOT NULL,
    vote_question   TEXT,
    vote_type       TEXT,
    vote_category   TEXT NOT NULL,
    result          TEXT,
    passed          BOOLEAN,
    bill_id         TEXT,              -- FK to dim_bill; NULL for pure nominations without PN id
    yea_total       INTEGER,
    nay_total       INTEGER,
    present_total   INTEGER,
    not_voting_total INTEGER,
    source_url      TEXT
);

CREATE TABLE IF NOT EXISTS fact_member_vote (
    vote_id     TEXT NOT NULL,
    bioguide_id TEXT NOT NULL,
    position    TEXT NOT NULL CHECK (position IN ('YEA', 'NAY', 'PRESENT', 'NOT_VOTING')),
    PRIMARY KEY (vote_id, bioguide_id)
);

CREATE TABLE IF NOT EXISTS bridge_vote_impact (
    vote_id       TEXT NOT NULL,
    impact_tag    TEXT NOT NULL,
    confidence    DOUBLE NOT NULL,
    classified_by TEXT NOT NULL CHECK (classified_by IN ('RULE', 'LLM', 'HUMAN')),
    PRIMARY KEY (vote_id, impact_tag)
);

-- Adjudicated valence: does a YEA on this (vote, impact_tag) advance the
-- measured axis (+1) or oppose it (-1)? This is INPUT data (a political
-- judgment), not a computed metric, so it is persisted — unlike signed
-- scores, which are always recomputed live at render time (AGENTS.md §8).
-- Decoupled from bridge_vote_impact so reclassify/promote never wipe it.
-- valence: +1 pro-axis on YEA, -1 anti-axis on YEA. 0/absent = not scoreable.
CREATE TABLE IF NOT EXISTS fact_vote_valence (
    vote_id        TEXT NOT NULL,
    impact_tag     TEXT NOT NULL,
    valence        INTEGER NOT NULL CHECK (valence IN (-1, 0, 1)),
    valence_source TEXT NOT NULL CHECK (valence_source IN ('RULE', 'LLM', 'HUMAN')),
    adjudicated_at_utc TIMESTAMP,
    PRIMARY KEY (vote_id, impact_tag)
);

-- Ordered rule table for vote_category derivation. Lower priority wins
-- (evaluated via MIN(priority) among matching regex rules).
CREATE TABLE IF NOT EXISTS ref_vote_category_rule (
    rule_id        INTEGER PRIMARY KEY,
    priority       INTEGER NOT NULL,
    vote_category  TEXT NOT NULL,
    question_regex TEXT,   -- NULL means match-any for this column
    type_regex     TEXT,   -- NULL means match-any for this column
    notes          TEXT
);

-- Opaque string metadata (upstream SHAs, refresh watermarks). Not metrics.
CREATE TABLE IF NOT EXISTS warehouse_meta (
    meta_key       TEXT PRIMARY KEY,
    meta_value     TEXT NOT NULL,
    updated_at_utc TIMESTAMP NOT NULL
);
