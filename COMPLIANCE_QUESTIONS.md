# Compliance questions for counsel review

This document lists open legal and compliance questions for outside counsel.
It does not provide answers. Operators should not treat any site copy as legal advice.

## FEC and federal campaign finance

- Does the site's sponsorship by Democrats for Virginia, combined with content
  naming federal candidates (incumbents and challengers in VA-1, VA-2, VA-5),
  trigger FEC disclaimer requirements on the site or on derivative social assets?
- If disclaimers are required, what exact language, placement, and typography
  apply to (a) the static site, (b) Open Graph images, and (c) shared links?
- Does publishing seat-win probabilities, fundraising totals, or voting scores
  about named candidates constitute "express advocacy" or "electioneering
  communications" under current FEC guidance?
- Are OpenFEC-derived fundraising displays on race pages treated as independent
  expenditure reporting, coordinated party activity, or neither?

## Coordination and in-kind contributions

- Does the publisher's caucus or party role create coordination issues when
  operators adjudicate vote valence or choose which roll calls enter the score?
- Is hosting, engineering time, or data infrastructure an in-kind contribution
  to any named federal candidate if the site highlights specific races?
- Should blind-coding workflow (`valence_review_queue.csv`, `coded_blind`) be
  documented for compliance review as a bias-control measure?

## State-level requirements

- Are there Virginia state-law disclosure or disclaimer requirements beyond FEC
  rules for this publisher and content mix?
- Do state registration or reporting obligations apply if the site is framed as
  "independent analysis" rather than a party committee site?

## Branding and neutrality claims

- Does "Democrats for Virginia" branding, alongside claims that methodology
  applies identically to both parties, create a fairness or substantiation risk
  that counsel should review?
- Should race-page optional disclaimers (`config/site_disclosure.yaml`) carry
  candidate-specific language counsel prepares per race?

## Corrections and data integrity

- What retention or correction policy does counsel recommend when adjudication
  errors or upstream roll-call corrections change published scores?
- See the public stub at `/corrections` on the site; finalize policy language
  before production promotion.

## Process

- Update `config/site_disclosure.yaml` only after counsel approves footer and
  race-page disclaimer text.
- Do not remove this file from the repository; add dated counsel memos or ticket
  references below when questions are resolved.

### Counsel log

| Date | Reviewer | Notes |
|------|----------|-------|
| _pending_ | | Initial question list (Prompt 16) |
