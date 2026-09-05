-- Re-derive vote_category for every fact_vote row from the current rule table.
-- Set-based counterpart to classify_vote_category.sql, which answers one row at
-- a time. vote_category is otherwise only ever assigned at load time, so a rule
-- change cannot reach rows already in the warehouse without this.
SELECT
  v.vote_id,
  v.chamber,
  v.vote_question,
  v.vote_category AS old_category,
  r.vote_category AS new_category
FROM fact_vote v
LEFT JOIN LATERAL (
  SELECT vote_category
  FROM ref_vote_category_rule
  WHERE (question_regex IS NULL OR regexp_matches(coalesce(v.vote_question, ''), question_regex))
    AND (type_regex IS NULL OR regexp_matches(coalesce(v.vote_type, ''), type_regex))
  ORDER BY priority ASC, rule_id ASC
  LIMIT 1
) r ON TRUE;
