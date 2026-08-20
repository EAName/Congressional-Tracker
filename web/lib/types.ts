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
