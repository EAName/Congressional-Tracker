-- Analytic / lookup indexes for the star schema.

CREATE INDEX IF NOT EXISTS idx_fact_member_vote_bioguide
    ON fact_member_vote (bioguide_id);

CREATE INDEX IF NOT EXISTS idx_fact_vote_date
    ON fact_vote (vote_date);

CREATE INDEX IF NOT EXISTS idx_fact_vote_category
    ON fact_vote (vote_category);

CREATE INDEX IF NOT EXISTS idx_fact_vote_chamber_roll
    ON fact_vote (chamber, congress, session, roll_number);

CREATE INDEX IF NOT EXISTS idx_fact_vote_valence_tag
    ON fact_vote_valence (impact_tag);
