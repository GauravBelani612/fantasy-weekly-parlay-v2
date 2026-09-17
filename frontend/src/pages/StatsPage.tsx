import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { useLeague, useLeagueStats } from "../api/hooks";
import type { BetTypeStat, LeagueStats, MemberStats, Streak } from "../api/types";
import { Avatar, ErrorNote, Panel, Spinner } from "../components/ui";

const pct = (rate: number | null) => (rate === null ? "—" : `${Math.round(rate * 100)}%`);
const record = (hits: number, misses: number) => `${hits}–${misses}`;
const count = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
const settled = (m: MemberStats) => m.hits + m.misses + m.voids > 0;

/** Names for a tile: all of them for a small tie, a count past that. */
function names(list: string[]): string {
  if (list.length <= 2) return list.join(" & ");
  if (list.length === 3) return `${list[0]}, ${list[1]} & ${list[2]}`;
  return `${list.length} tied`;
}

// ------------------------------------------------------------------ pieces

function StatTile({
  label,
  value,
  detail,
  wordy = false,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  /** A name rather than a figure: smaller, and allowed to wrap rather than clip. */
  wordy?: boolean;
}) {
  return (
    <div className="rounded-lg border border-edge bg-input px-4 py-3">
      <p className="text-xs text-slate-500">{label}</p>
      <p
        className={`mt-1 font-semibold break-words text-white ${wordy ? "text-base leading-snug" : "text-2xl"}`}
      >
        {value}
      </p>
      {detail && <p className="mt-0.5 text-xs text-slate-400">{detail}</p>}
    </div>
  );
}

/** Hit or miss never rides on color alone: red and green sit close for common colorblindness,
 *  so every streak carries an icon and the word. */
function StreakChip({ streak }: { streak: Streak | null }) {
  if (!streak) return <span className="text-slate-600">&mdash;</span>;
  const hit = streak.result === "hit";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold whitespace-nowrap ${
        hit
          ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
          : "border-red-500/40 bg-red-500/15 text-red-300"
      }`}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="h-3 w-3"
      >
        {hit ? <path d="M3.5 8.5l3 3 6-7" /> : <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />}
      </svg>
      {count(streak.length, hit ? "hit" : "miss", hit ? "hits" : "misses")}
    </span>
  );
}

/** A single ratio against 100%. Same-hue track; the percentage beside it carries the value. */
function Meter({ rate }: { rate: number | null }) {
  return (
    <div aria-hidden="true" className="h-1.5 w-full overflow-hidden rounded-[3px] bg-emerald-500/15">
      <div
        className="h-full rounded-r-[3px] bg-emerald-500"
        style={{ width: `${Math.round((rate ?? 0) * 100)}%` }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ sections

function YourSeason({ me, rank, ranked }: { me: MemberStats; rank: number; ranked: number }) {
  if (!settled(me)) {
    return (
      <Panel>
        <h2 className="text-lg font-semibold text-white">Your season</h2>
        <p className="mt-1 text-sm text-slate-400">
          None of your legs have been graded yet. Your hit rate, streaks and record fill in as
          games finish.
        </p>
        {me.times_funded > 0 && (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
            <StatTile label="Times paying" value={me.times_funded} />
          </div>
        )}
      </Panel>
    );
  }

  const voids = me.voids ? ` · ${count(me.voids, "void")}` : "";

  return (
    <Panel>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-white">Your season</h2>
        <p className="text-sm text-slate-500">
          #{rank} of {ranked} on hits
        </p>
      </div>

      {/* The page's one hero figure: the number people open this to find. */}
      <div className="mt-3 flex flex-wrap items-end gap-x-4 gap-y-1">
        <p className="text-5xl leading-none font-semibold text-white">{pct(me.hit_rate)}</p>
        <p className="pb-1 text-sm text-slate-400">
          hit rate &middot; <span className="tabular-nums">{record(me.hits, me.misses)}</span>
          {voids}
        </p>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <StatTile label="Current streak" value={<StreakChip streak={me.current_streak} />} />
        <StatTile
          label="Longest hit streak"
          value={me.longest_hit_streak}
          detail={me.longest_hit_streak === 1 ? "leg" : "in a row"}
        />
        <StatTile
          label="Parlays won"
          value={me.parlays_won}
          detail={`of ${count(me.parlays_played, "parlay")} played`}
        />
        <StatTile label="Times paying" value={me.times_funded} />
        <StatTile
          label="Parlay killer"
          value={me.only_miss}
          detail={me.only_miss === 1 ? "week yours was the only miss" : "weeks yours was the only miss"}
        />
        <StatTile
          label="Best bet type"
          value={me.best_bet_type ? me.best_bet_type.label : "—"}
          detail={
            me.best_bet_type
              ? `${pct(me.best_bet_type.hit_rate)} · ${record(me.best_bet_type.hits, me.best_bet_type.misses)}`
              : "Needs 2+ graded legs of one type"
          }
          wordy={Boolean(me.best_bet_type)}
        />
      </div>
    </Panel>
  );
}

function LeagueHighlights({ stats }: { stats: LeagueStats }) {
  const l = stats.league;
  const tiles: ReactNode[] = [];

  if (l.parlays_won + l.parlays_lost > 0) {
    tiles.push(
      <StatTile
        key="cashed"
        label="Parlays cashed"
        value={l.parlays_won}
        detail={`of ${l.parlays_won + l.parlays_lost} settled · ${pct(l.cash_rate)}`}
      />,
    );
  }
  if (l.avg_hits_per_week !== null && l.avg_legs_per_week !== null) {
    tiles.push(
      <StatTile
        key="avg"
        label="Avg legs hit per week"
        value={l.avg_hits_per_week}
        detail={`of ${l.avg_legs_per_week} legs · ${count(l.weeks_complete, "week")}`}
      />,
    );
  }
  if (l.best_week) {
    tiles.push(
      <StatTile
        key="best"
        label="Most legs hit in a week"
        value={l.best_week.hits}
        detail={`Week ${l.best_week.bet_week} · ${l.best_week.hits} of ${l.best_week.legs}`}
      />,
    );
  }
  if (l.hit_rate !== null) {
    tiles.push(
      <StatTile
        key="rate"
        label="League hit rate"
        value={pct(l.hit_rate)}
        detail={record(l.legs_hit, l.legs_missed)}
      />,
    );
  }

  const mostHits = Math.max(0, ...stats.members.map((m) => m.hits));
  if (mostHits > 0) {
    const leaders = stats.members.filter((m) => m.hits === mostHits).map((m) => m.display_name);
    tiles.push(
      <StatTile
        key="leader"
        label="Most hit legs"
        value={names(leaders)}
        detail={count(mostHits, "hit")}
        wordy
      />,
    );
  }
  if (l.top_payers.length) {
    const times = l.top_payers[0].times;
    tiles.push(
      <StatTile
        key="payer"
        label="Most often paying"
        value={names(l.top_payers.map((p) => p.display_name))}
        detail={`paid ${count(times, "time")}`}
        wordy
      />,
    );
  }
  if (l.parlays_lost > 0) {
    tiles.push(
      <StatTile
        key="close"
        label="One leg away"
        value={l.one_leg_away}
        detail={l.one_leg_away === 1 ? "parlay lost by a single leg" : "parlays lost by a single leg"}
      />,
    );
  }

  return (
    <Panel>
      <h2 className="text-lg font-semibold text-white">League</h2>
      {tiles.length ? (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">{tiles}</div>
      ) : (
        <p className="mt-1 text-sm text-slate-400">Nothing to show until the first parlay opens.</p>
      )}
    </Panel>
  );
}

function Leaderboard({ members }: { members: MemberStats[] }) {
  return (
    <Panel>
      <h2 className="text-lg font-semibold text-white">Leaderboard</h2>
      <p className="mt-0.5 text-xs text-slate-500">
        Players appear once one of their legs is graded. Voids don&apos;t count toward hit %.
      </p>
      {/* Wide table, narrow phone: it scrolls inside its own box, never the page. */}
      <div className="-mx-5 mt-3 overflow-x-auto px-5">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th scope="col" className="w-8 pb-2 font-medium">#</th>
              <th scope="col" className="pb-2 font-medium">Player</th>
              <th scope="col" className="pb-2 text-right font-medium">Hits</th>
              <th scope="col" className="pb-2 text-right font-medium">Misses</th>
              <th scope="col" className="pb-2 text-right font-medium">Hit %</th>
              <th scope="col" className="pb-2 pl-4 font-medium">Streak</th>
              <th scope="col" className="pb-2 text-right font-medium">Won</th>
              <th scope="col" className="pb-2 text-right font-medium">Paid</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {members.map((m, index) => (
              <tr
                key={m.member_id}
                className={`border-t border-edge ${m.is_you ? "bg-emerald-500/5" : ""}`}
              >
                <td className="py-2.5 text-slate-500">{index + 1}</td>
                <td className="py-2.5">
                  <span className="flex items-center gap-2 whitespace-nowrap text-slate-100">
                    <Avatar
                      member={{ display_name: m.display_name, avatar_url: m.avatar_url }}
                      size={22}
                    />
                    {m.display_name}
                    {m.is_you && <span className="text-xs text-emerald-400">you</span>}
                  </span>
                </td>
                <td className="py-2.5 text-right font-semibold text-slate-100">{m.hits}</td>
                <td className="py-2.5 text-right text-slate-300">{m.misses}</td>
                <td className="py-2.5 text-right text-slate-300">{pct(m.hit_rate)}</td>
                <td className="py-2.5 pl-4">
                  <StreakChip streak={m.current_streak} />
                </td>
                <td className="py-2.5 text-right text-slate-300">{m.parlays_won}</td>
                <td className="py-2.5 text-right text-slate-300">{m.times_funded}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function BetTypes({ rows }: { rows: BetTypeStat[] }) {
  return (
    <Panel>
      <h2 className="text-lg font-semibold text-white">Hit rate by bet type</h2>
      <p className="mt-0.5 text-xs text-slate-500">Across every graded leg in the league.</p>
      <ul className="mt-4 space-y-3">
        {rows.map((row) => (
          <li
            key={row.label}
            className="grid grid-cols-[6.5rem_minmax(0,1fr)_auto] items-center gap-3 text-sm"
          >
            <span className="text-slate-200">{row.label}</span>
            <Meter rate={row.hit_rate} />
            <span className="text-right text-xs whitespace-nowrap text-slate-400 tabular-nums">
              <span className="text-sm font-semibold text-slate-100">{pct(row.hit_rate)}</span>
              {" · "}
              {record(row.hits, row.misses)}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// ------------------------------------------------------------------ page

export function StatsPage() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const league = useLeague(leagueId);
  const stats = useLeagueStats(leagueId);

  if (stats.isLoading) return <Spinner />;
  if (stats.error) return <ErrorNote error={stats.error} />;
  if (!stats.data) return null;

  const data = stats.data;
  const ranked = data.members.filter(settled);
  const me = data.members.find((m) => m.is_you);
  const nothingGraded = data.league.legs_hit + data.league.legs_missed === 0;

  return (
    <div className="space-y-5">
      <div>
        <Link to={`/leagues/${leagueId}`} className="text-sm text-slate-400 hover:text-slate-200">
          &lsaquo; {league.data?.name ?? "Back"}
        </Link>
        <h1 className="mt-1 text-2xl font-bold text-white">Stats</h1>
        <p className="text-sm text-slate-500">{data.season} season</p>
      </div>

      {nothingGraded && (
        <p className="rounded-lg border border-edge bg-panel px-4 py-3 text-sm text-slate-400">
          No legs have been graded yet. Everything here fills in as games finish.
        </p>
      )}

      {me && (
        <YourSeason
          me={me}
          rank={ranked.findIndex((m) => m.member_id === me.member_id) + 1}
          ranked={ranked.length}
        />
      )}
      <LeagueHighlights stats={data} />
      {ranked.length > 0 && <Leaderboard members={ranked} />}
      {data.league.by_bet_type.length > 0 && <BetTypes rows={data.league.by_bet_type} />}
    </div>
  );
}
