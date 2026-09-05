-- Seed / refresh vote-category rules. Idempotent via DELETE + INSERT of known ids.
-- Matching: a rule matches when (question_regex IS NULL OR question ~* regex)
-- AND (type_regex IS NULL OR vote_type ~* regex). Lowest priority number wins.

DELETE FROM ref_vote_category_rule WHERE rule_id BETWEEN 1 AND 20;

INSERT INTO ref_vote_category_rule (rule_id, priority, vote_category, question_regex, type_regex, notes) VALUES
  (1,  10, 'SUSPENSION',          '(?i)suspension of the rules|suspend(ing)? the rules|passage under suspension', NULL, 'Two-thirds threshold; keep distinct from PASSAGE'),
  (2,  20, 'MOTION_TO_RECOMMIT',  '(?i)motion to recommit', NULL, NULL),
  (3,  30, 'CLOTURE',             '(?i)cloture', NULL, NULL),
  (4,  40, 'NOMINATION',          '(?i)nomination|confirm(ation)?', NULL, 'Personnel votes (incl. SBA/agency)'),
  (5,  50, 'AMENDMENT',           '(?i)amendment|agreeing to the amendment', NULL, NULL),
  (6,  60, 'PASSAGE',             '(?i)on passage|passage of the bill|agreeing to the (bill|resolution|conference report)', NULL, 'Ordinary passage / adoption'),
  (7,  70, 'PROCEDURAL',          '(?i)previous question|motion to (adjourn|table|proceed|discharge)|ordering the previous|consideration of|motion to concur', NULL, NULL),
  (9,  65, 'PASSAGE',             '(?i)^on the joint resolution', NULL, 'Senate final passage on a joint resolution. The House says "On Passage" and is caught by rule 6; the Senate says "On the Joint Resolution" and was falling through to the rule-8 fallback, so the same CRA disapproval was scoreable in one chamber and invisible in the other. Anchored: "On the Motion to Proceed" must stay procedural. Joint resolutions only, since they carry force of law; simple and concurrent resolutions do not.'),
  (8, 100, 'PROCEDURAL',          NULL, NULL, 'Fallback when no higher-priority rule matches');
