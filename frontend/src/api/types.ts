// Mirrors backend/app/schemas.py. Keep the two in sync.

export type RoundStatus = "upcoming" | "open" | "locked";
export type LegResult = "pending" | "hit" | "miss" | "push" | "void";
export type RoundOutcome = "pending" | "won" | "lost" | "void";

export interface User {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
}

export interface SleeperLink {
  sleeper_user_id: string;
  sleeper_username: string;
  sleeper_display_name: string | null;
  avatar_url: string | null;
}

export interface Me {
  user: User;
  sleeper: SleeperLink | null;
}

export interface SleeperLeague {
  sleeper_league_id: string;
  name: string;
  season: string;
  total_rosters: number;
  avatar_url: string | null;
  already_imported: boolean;
  /** Never finished being set up in Sleeper, so almost certainly an abandoned twin
   *  of a real league. Hidden from the list unless asked for. */
  unconfigured: boolean;
}

export interface Member {
  id: string;
  display_name: string;
  team_name: string | null;
  avatar_url: string | null;
  sleeper_roster_id: number;
  role: string;
  has_app_account: boolean;
  is_you: boolean;
}

export interface League {
  id: string;
  sleeper_league_id: string;
  name: string;
  season: string;
  avatar_url: string | null;
  total_rosters: number;
  lock_offset_minutes: number;
  timezone: string;
  first_scored_week: number;
  last_scored_week: number;
  has_discord_webhook: boolean;
  your_role: string | null;
}

export interface LeagueDetail extends League {
  members: Member[];
}

export interface Leg {
  id: string;
  member_id: string;
  member_name: string;
  member_avatar_url: string | null;
  raw_text: string;
  result: LegResult;
  american_odds: number | null;
  created_at: string;
  updated_at: string;
  is_you: boolean;
}

export interface Round {
  id: string;
  league_id: string;
  season: string;
  scored_week: number;
  bet_week: number;
  status: RoundStatus;
  opens_at: string;
  locks_at: string;

  loser: Member | null;
  loser_points: number | null;
  tie_roster_ids: number[] | null;
  loser_has_app_account: boolean;

  outcome: RoundOutcome;
  final_odds: string | null;
  stake_cents: number | null;
  payout_cents: number | null;
  notes: string | null;

  legs: Leg[];
  awaiting: Member[];
  submitted_count: number;
  eligible_count: number;
  your_leg: Leg | null;
  you_can_submit: boolean;
}
