export type Party = "Democrat" | "Republican" | null;

export interface Score {
  bioguide_id: string;
  full_name: string;
  party: Party;
  chamber: string;
  district_number: number | null;
  theme: string;
  signed_score: number;
  wilson_low: number;
  wilson_high: number;
  n_contested: number;
  n_yea: number;
  n_nay: number;
  absence_rate: number | null;
  sufficient: boolean;
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
