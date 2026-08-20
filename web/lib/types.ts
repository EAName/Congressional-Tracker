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
  district: number;
  election_date: string;
  status: "tracked" | "watch";
  incumbent: RaceCandidate;
  challenger: RaceCandidate;
  days_until_election: number;
}

export interface RacesDoc {
  version: number;
  map_version: string;
  election_date: string;
  as_of: string;
  days_until_election: number;
  races: RaceEntry[];
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
  REGULATORY_BURDEN: "Regulatory burden",
  HEALTH_COSTS: "Health costs",
  ACCESS_TO_CAPITAL: "Access to capital",
  TAX_BURDEN: "Tax burden",
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

export interface MethodologyDoc {
  repo_url: string;
  votes_url: string;
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
}
