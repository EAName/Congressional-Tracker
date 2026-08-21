export type Party = "Democrat" | "Republican" | null;

export type ScoreMode = "eb" | "raw";

export interface Score {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  theme: string;
  signed_score: number | null;
  wilson_low: number | null;
  wilson_high: number | null;
  raw_score: number | null;
  wilson_lo: number | null;
  wilson_hi: number | null;
  eb_score: number;
  cred_lo: number;
  cred_hi: number;
  n: number;
  k: number;
  n_contested: number;
  n_yea: number;
  n_nay: number;
  n_pro?: number;
  absence_rate: number | null;
  sufficient: boolean;
  prior_alpha: number;
  prior_beta: number;
  prior_source: string;
  prior_only: boolean;
}

export interface PartyBaseline {
  theme: string;
  party: string;
  eb_center: number;
  weighted_median: number | null;
  prior_alpha: number;
  prior_beta: number;
  prior_source: string;
  n_members: number;
}

export interface DefectionVote {
  vote_id: string;
  vote_date: string;
  bill_id: string | null;
  summary: string | null;
  position: string;
  source_link: string | null;
}

export interface Deviation {
  bioguide_id: string;
  full_name: string;
  party: Party;
  district_number: number | null;
  theme: string;
  signed_score: number;
  party_baseline: number;
  deviation: number;
  n_contested: number;
  defection_votes: DefectionVote[];
}

export interface Meta {
  generated_at_utc: string;
  map_version: string;
  axis: { name: string; description: string };
  themes: string[];
  sufficient_min: number;
  estimate_default?: ScoreMode;
  baselines?: PartyBaseline[];
  election_date?: string;
  days_until_election?: number;
  races_as_of?: string;
}

export interface RaceCandidate {
  name: string;
  party: "Democrat" | "Republican";
  fec_candidate_id: string;
  bioguide_id?: string | null;
  prior_federal_service?: Array<{
    chamber: string;
    congresses: number[];
    bioguide_id: string;
  }> | null;
}

export interface RaceEntry {
  race_id: string;
  chamber: "House" | "Senate";
  /** Null for the statewide Senate race. */
  district: number | null;
  election_date: string;
  status: "tracked" | "watch";
  incumbent: RaceCandidate;
  challenger: RaceCandidate;
  days_until_election: number;
  label?: string;
}

/** `VA-2` for House seats, `VA-Sen` for the statewide race. */
export const raceLabel = (entry: Pick<RaceEntry, "chamber" | "district" | "label">): string =>
  entry.label ?? (entry.chamber === "Senate" ? "VA-Sen" : `VA-${entry.district}`);

export interface RacesDoc {
  version: number;
  map_version: string;
  election_date: string;
  as_of: string;
  days_until_election: number;
  races: RaceEntry[];
}

export interface SeatDecomposition {
  intercept: number;
  lean_rel_dem: number;
  inc_dem: number;
  midterm_dem: number;
  log_ratio_dem: number;
  qual_dem: number;
  nat_env: number;
  polls: number;
}

export interface SeatRace {
  race_id: string;
  district: number;
  as_of: string;
  model_version: string;
  prob_dem: number;
  prob_rep: number;
  mu_dem_two_party: number;
  mu_fundamentals: number;
  share_lo: number;
  share_hi: number;
  sigma: number;
  blend: "fundamentals_only" | "fundamentals_plus_polls" | string;
  plain_language: string;
  takeaway?: string;
  flip_threshold_pp?: number | null;
  env_probs?: number[];
  env_mu?: number[];
  decomposition: SeatDecomposition;
  n_polls: number;
  meta?: {
    lean_status?: string;
    environment_source?: string;
    dem_receipts?: number;
    rep_receipts?: number;
  };
}

export interface EnvGrid {
  margin_pp: number[];
  default_margin_pp: number;
  step: number;
  min: number;
  max: number;
  probs: Record<string, number[]>;
}

export interface SeatsDoc {
  model_version: string;
  as_of: string;
  races: SeatRace[];
  /** Tracked races the House-fit model does not score (e.g. the statewide Senate race). */
  unmodeled_races?: string[];
  env_grid?: EnvGrid;
  log: Array<{ race_id: string; date: string; prob_dem: string; model_version: string }>;
}

export interface FecCandidate {
  fec_candidate_id: string;
  race_id: string;
  role: string;
  name: string;
  party: string;
  receipts: number | null;
  cash_on_hand: number | null;
  small_dollar_share: number | null;
  independent_expenditures_support: number;
  independent_expenditures_oppose: number;
}

export interface FecDoc {
  latest_path: string | null;
  snapshot: {
    snapshot_date: string;
    candidates: FecCandidate[];
  } | null;
}

export interface Member {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  partisan_lean: string | null;
  is_target: boolean | null;
}

export const THEME_LABELS: Record<string, string> = {
  INPUT_COSTS: "Input costs",
  REGULATORY_BURDEN: "Compliance and reporting",
  HEALTH_COSTS: "Health costs",
  ACCESS_TO_CAPITAL: "Access to capital",
  TAX_BURDEN: "Taxes and credits",
  WORKFORCE: "Workforce",
  FEDERAL_CONTRACTING: "Federal contracting",
};

export const themeLabel = (t: string): string =>
  THEME_LABELS[t] ?? t.replace(/_/g, " ").toLowerCase();

export const shortName = (n: string): string =>
  n.replace(", Jr.", "").replace(" III", "").replace(' "Bobby"', "");

export interface WorkedExample {
  bioguide_id: string;
  full_name: string;
  party: string | null;
  chamber: string;
  district_number: number | null;
  theme: string;
  k: number;
  n: number;
  p_raw: number;
  raw_score: number;
  wilson_lo: number;
  wilson_hi: number;
  prior_alpha: number;
  prior_beta: number;
  prior_source: string;
  prior_mean: number;
  post_alpha: number;
  post_beta: number;
  post_mean: number;
  eb_score: number;
  cred_lo: number;
  cred_hi: number;
  shrinkage: number;
}

export interface SeparationResult {
  delta_signed: number;
  power_target: number;
  n_sims: number;
  cred_level: number;
  p_true: number[];
  signed_true: number[];
  prior_alpha: number;
  prior_beta: number;
  prior_source: string;
  n_needed: number | null;
  power_at_n: number | null;
  power_at_max_n?: number;
  max_n: number;
  reached: boolean;
}

export interface TimePoint {
  date: string;
  eb: number;
  lo: number;
  hi: number;
  n: number;
  k: number;
}

export interface TimeSeriesCell {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  theme: string;
  points: TimePoint[];
}

export interface BiggestMover {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  theme: string;
  delta: number;
  start_score: number;
  end_score: number;
  start_date: string;
  end_date: string;
  start_n: number;
  end_n: number;
  window_days: number;
}

export interface TimeSeriesDoc {
  as_of: string | null;
  window_days: number;
  series: TimeSeriesCell[];
  biggest_mover: BiggestMover | null;
}

export interface IrtMember {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  theta_mean: number;
  theta_hdi_lo: number;
  theta_hdi_hi: number;
  is_anchor_low: boolean;
  is_anchor_high: boolean;
}

export interface IrtVote {
  vote_id: string;
  bill_id: string | null;
  date: string;
  themes: string[];
  source_url: string;
  b_mean: number;
  gamma_mean: number;
  gamma_hdi: number[];
  gamma_hdi_lo: number;
  gamma_hdi_hi: number;
}

export interface IrtDoc {
  model: string;
  identification: { low_anchor: string; high_anchor: string; method: string; rule: string };
  diagnostics: { rhat_max: number; ess_bulk_min_theta: number; n_draws: number; n_chains: number };
  gamma_median_abs: number;
  members: IrtMember[];
  votes: IrtVote[];
  n_members: number;
  n_items: number;
}

export interface CosponsorshipDoc {
  never_blended: boolean;
  rows: CosponsorScore[];
}

export interface CosponsorScore {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  theme: string;
  eb_score: number;
  cred_lo: number;
  cred_hi: number;
  raw_score: number | null;
  n: number;
  k: number;
  prior_source: string;
  sufficient: boolean;
}

export interface ChangelogEntry {
  sha: string;
  date: string;
  subject: string;
}

export interface SymmetryAuditThemeRow {
  theme: string;
  n_rollcalls_dem: number;
  n_rollcalls_rep: number;
  dem_caucus_advancing_share: number | null;
  rep_caucus_advancing_share: number | null;
  gap_pp: number | null;
  note: string;
}

export interface SymmetryAuditDoc {
  inclusion_spec_version?: string;
  spec_path?: string;
  excluded_path?: string;
  excluded_counts_by_reason?: Record<string, number>;
  caucus_advancing_by_theme?: SymmetryAuditThemeRow[];
  max_caucus_advancing_gap_pp?: number;
  n_depth_by_party?: {
    by_party: Record<
      string,
      { n_cells: number; median: number; min: number; max: number }
    >;
    median_gap: number | null;
  };
  ci_width_at_matched_n?: Array<{
    n_contested: number;
    dem_median_width: number;
    rep_median_width: number;
    gap: number;
  }>;
  max_ci_width_gap?: number;
  exclusion_by_sponsor_party?: {
    totals_by_sponsor_party: Record<string, number>;
    by_reason: Record<string, Record<string, number>>;
    democrat_share_pp: number | null;
    rate_gap_pp: number | null;
  };
  coded_blind?: {
    n_units: number;
    false_count?: number;
    false_share?: number | null;
    false_share_pp?: number | null;
  };
  thresholds?: Record<string, number>;
  falsification?: Record<
    string,
    { trip: string; action: string }
  >;
  flags?: Record<string, boolean>;
  any_tripped?: boolean;
}

export interface MethodologyDoc {
  repo_url: string;
  votes_url: string;
  votes_excluded_url?: string;
  inclusion_spec_url?: string;
  reproduce: string[];
  scoreable: {
    axis_name: string;
    axis_description: string;
    include_categories: string[];
    exclude_categories: string[];
    exclude_rule_resolutions: boolean;
    min_contested: number;
    wilson_z: number;
    eb_method: string;
    eb_min_caucus: number;
    eb_fallback_alpha: number;
    eb_fallback_beta: number;
  };
  baselines: PartyBaseline[];
  worked_example: WorkedExample | null;
  separation: {
    weakly_informative: SeparationResult;
    worked_example_prior: SeparationResult | null;
  };
  changelog: ChangelogEntry[];
  symmetry_audit?: SymmetryAuditDoc;
}

export interface DisclosureDoc {
  publisher: string;
  footer: {
    paragraphs: string[];
    methodology_label: string;
    methodology_href: string;
    about_label?: string;
    about_href?: string;
    corrections_label: string;
    corrections_href: string;
  };
  race_page: {
    default_disclaimer: string;
    by_race_id: Record<string, string>;
  };
}

export interface HeadToHeadScore {
  bioguide_id?: string;
  full_name?: string;
  party?: string;
  eb_score?: number | null;
  cred_lo?: number | null;
  cred_hi?: number | null;
  n_contested?: number | null;
  sufficient?: boolean;
  historical?: boolean;
  congress_era?: string | null;
}

export interface HeadToHeadTheme {
  theme: string;
  incumbent: HeadToHeadScore | null;
  challenger: HeadToHeadScore | null;
}

export interface HeadToHeadRace {
  status: "ready" | "pending_adjudication" | "no_federal_record";
  era_caption: string | null;
  congress_eras?: string[];
  themes: HeadToHeadTheme[];
  incumbent_only?: boolean;
}

export interface HeadToHeadDoc {
  races: Record<string, HeadToHeadRace>;
}

export interface BrandDoc {
  site_name: string;
  site_name_note?: string;
  tagline: string;
  product_name: string;
  domain: string;
  domain_note?: string;
  canonical_base: string;
  publisher_line: string;
  github: {
    repo_url: string;
    repo_name: string;
    org: string;
  };
  social: Record<string, string>;
  legacy?: Record<string, string>;
  redirect_paths?: string[];
  status?: string;
}

export interface AboutSection {
  heading: string;
  paragraphs: string[];
}

export interface AboutDoc {
  title: string;
  intro: string;
  sections: AboutSection[];
  repo_url: string;
  methodology_href: string;
  symmetry_href: string;
}

export interface GenericBallotPoint {
  date: string;
  dem_two_party: number;
  lo: number;
  hi: number;
  effective_n_polls: number;
  sd?: number;
}

export interface GenericBallotPoll {
  pollster: string;
  sponsor: string;
  date: string;
  start_date: string;
  end_date: string;
  n: number;
  population: "lv" | "rv" | "a";
  dem: number;
  rep: number;
  dem_two_party: number;
  partisan: string;
  source_url: string;
}

export interface GenericBallotDoc {
  version: number;
  as_of: string;
  n_polls: number;
  min_polls: number;
  band_coverage: number;
  half_life_days: number;
  sample_type_offsets_are_priors: boolean;
  series: GenericBallotPoint[];
  environment_gate?: {
    ok: boolean;
    n_polls: number;
    effective_n_polls: number;
    /** Largest move in the average, in margin points, from dropping any one poll. */
    single_poll_influence_pp: number | null;
    max_single_poll_influence_pp: number;
    min_polls: number;
    reasons: string[];
  };
  house_effects: Record<string, number>;
  polls: GenericBallotPoll[];
  current: {
    date: string;
    dem: number;
    rep: number;
    dem_two_party: number;
    margin_pp: number;
    lo: number;
    hi: number;
  } | null;
  status?: string;
}

export interface SenateRace {
  race_id: string;
  state_po: string;
  as_of: string;
  model_version: string;
  prob_dem: number;
  prob_rep: number;
  mu_dem_two_party: number;
  mu_fundamentals: number;
  share_lo: number;
  share_hi: number;
  sigma: number;
  blend: string;
  plain_language: string;
  takeaway: string;
  flip_threshold_pp: number | null;
  n_polls: number;
  decomposition: Record<string, number>;
  meta: { lean_status: string; lean_rel_dem: number; environment_source: string };
  env_probs: number[];
  env_mu: number[];
}

export interface SenateCycleScore {
  year: number;
  n: number;
  brier_model: number;
  brier_lean_swing: number;
  brier_always_incumbent: number;
}

export interface SenateDoc {
  model_version: string;
  as_of: string;
  sigma_fundamentals: number;
  env_grid?: EnvGrid;
  races: SenateRace[];
  fit: {
    n_train: number;
    cycles: number[];
    cv: {
      scheme: string;
      n: number;
      brier_model: number;
      brier_lean_swing: number;
      brier_always_incumbent: number;
      per_cycle: SenateCycleScore[];
    };
  };
}
