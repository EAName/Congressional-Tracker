-- Classify vote_question / vote_type using ref_vote_category_rule.
-- Patterns use (?i) where case-insensitivity is required. DuckDB regexp_matches
-- is a substring search for ordinary patterns.

SELECT vote_category
FROM ref_vote_category_rule
WHERE (question_regex IS NULL OR regexp_matches(coalesce(?, ''), question_regex))
  AND (type_regex IS NULL OR regexp_matches(coalesce(?, ''), type_regex))
ORDER BY priority ASC, rule_id ASC
LIMIT 1;
