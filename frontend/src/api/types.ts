// Mirrors backend/app/schemas.py. Keep the two in sync.

export type RoundStatus = "upcoming" | "open" | "locked";
export type LegResult =
  | "pending"
  | "hit"
  | "miss"
  | "void"
  /** No line anywhere: the payer records one, or settles the leg by hand. */
  | "needs_line"
  /** Couldn't be matched to a game or a player; a person decides. */
  | "unresolved";
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
  /** How the leg was understood, e.g. "Chase Brown (CIN) · anytime TD". */
  read_as: string | null;
  /** Why it got its result: "Jordan Love: 247 passing yds, line over 224.5". */
  grade_detail: string | null;
  graded_by: "espn" | "manual" | null;
  payer_line: number | null;
  needs_line: boolean;
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

// ---------------------------------------------------------------- stats

export interface Streak {
  result: "hit" | "miss";
  length: number;
}

export interface BetTypeStat {
  label: string;
  hits: number;
  misses: number;
  hit_rate: number | null;
}

export interface LeagueTotals {
  /** Weeks locked with every leg settled; the per-week averages use only these. */
  weeks_complete: number;
  legs_hit: number;
  legs_missed: number;
  hit_rate: number | null;
  avg_hits_per_week: number | null;
  avg_legs_per_week: number | null;
  best_week: { bet_week: number; hits: number; legs: number } | null;
  parlays_won: number;
  parlays_lost: number;
  cash_rate: number | null;
  /** Lost parlays where exactly one leg missed. */
  one_leg_away: number;
  by_bet_type: BetTypeStat[];
  /** Everyone tied for funding the most parlays. */
  top_payers: { member_id: string; display_name: string; times: number }[];
}

export interface MemberStats {
  member_id: string;
  display_name: string;
  avatar_url: string | null;
  is_you: boolean;
  hits: number;
  misses: number;
  voids: number;
  hit_rate: number | null;
  current_streak: Streak | null;
  longest_hit_streak: number;
  parlays_played: number;
  parlays_won: number;
  times_funded: number;
  /** Finished weeks where this member's leg was the only miss. */
  only_miss: number;
  best_bet_type: BetTypeStat | null;
}

export interface LeagueStats {
  season: string;
  league: LeagueTotals;
  /** Leaderboard order: most hits, then hit rate. */
  members: MemberStats[];
}
