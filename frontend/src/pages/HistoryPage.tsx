import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useLeague, useRecordResult, useRoundHistory } from "../api/hooks";
import type { Round } from "../api/types";
import { Avatar, Button, ErrorNote, Panel, Spinner } from "../components/ui";

const OUTCOME_STYLES: Record<string, string> = {
  won: "text-emerald-300 border-emerald-500/40 bg-emerald-500/10",
  lost: "text-red-300 border-red-500/40 bg-red-500/10",
  void: "text-slate-300 border-slate-500/40 bg-slate-500/10",
  pending: "text-slate-400 border-edge-strong",
};

function money(cents: number | null): string | null {
  if (cents === null) return null;
  return `$${(cents / 100).toFixed(2)}`;
}

function ResultForm({ round, leagueId }: { round: Round; leagueId: string }) {
  const record = useRecordResult(leagueId, round.id);
  const [outcome, setOutcome] = useState(round.outcome);
  const [odds, setOdds] = useState(round.final_odds ?? "");
  const [stake, setStake] = useState(round.stake_cents ? String(round.stake_cents / 100) : "");
  const [payout, setPayout] = useState(round.payout_cents ? String(round.payout_cents / 100) : "");

  const toCents = (value: string) =>
    value.trim() === "" ? null : Math.round(Number(value) * 100);

  return (
    <form
      className="mt-3 grid grid-cols-2 gap-2 border-t border-edge pt-3 sm:grid-cols-4"
      onSubmit={(event) => {
        event.preventDefault();
        record.mutate({
          outcome,
          final_odds: odds.trim() || null,
          stake_cents: toCents(stake),
          payout_cents: toCents(payout),
        });
      }}
    >
      <label className="text-xs text-slate-500">
        Outcome
        <select
          value={outcome}
          onChange={(event) => setOutcome(event.target.value as Round["outcome"])}
          className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-2 py-1.5 text-sm text-slate-100"
        >
          <option value="pending">Pending</option>
          <option value="won">Won</option>
          <option value="lost">Lost</option>
          <option value="void">Void</option>
        </select>
      </label>
      <label className="text-xs text-slate-500">
        Odds
        <input
          value={odds}
          onChange={(event) => setOdds(event.target.value)}
          placeholder="+1250"
          className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-2 py-1.5 text-sm text-slate-100"
        />
      </label>
      <label className="text-xs text-slate-500">
        Stake ($)
        <input
          value={stake}
          onChange={(event) => setStake(event.target.value)}
          inputMode="decimal"
          placeholder="20"
          className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-2 py-1.5 text-sm text-slate-100"
        />
      </label>
      <label className="text-xs text-slate-500">
        Payout ($)
        <input
          value={payout}
          onChange={(event) => setPayout(event.target.value)}
          inputMode="decimal"
          placeholder="270"
          className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-2 py-1.5 text-sm text-slate-100"
        />
      </label>
      <div className="col-span-2 sm:col-span-4">
        <Button type="submit" disabled={record.isPending}>
          {record.isPending ? "Saving..." : "Save result"}
        </Button>
        <ErrorNote error={record.error} />
      </div>
    </form>
  );
}

function RoundCard({ round, leagueId }: { round: Round; leagueId: string }) {
  const canRecord = round.loser?.is_you || round.legs.some((leg) => leg.is_you);

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-white">
          Week {round.bet_week} parlay
          <span className="ml-2 text-xs font-normal text-slate-500">
            (from week {round.scored_week} scores)
          </span>
        </h2>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize ${
            OUTCOME_STYLES[round.outcome] ?? OUTCOME_STYLES.pending
          }`}
        >
          {round.outcome}
        </span>
      </div>

      {round.loser && (
        <div className="mt-3 flex items-center gap-2 text-sm text-slate-400">
          <Avatar member={round.loser} size={22} />
          <span>
            Funded by <span className="text-slate-200">{round.loser.display_name}</span>
            {round.loser_points !== null && ` (${round.loser_points.toFixed(2)} pts)`}
          </span>
        </div>
      )}

      {(round.final_odds || round.stake_cents !== null || round.payout_cents !== null) && (
        <p className="mt-2 text-sm text-slate-400">
          {round.final_odds && <span className="mr-3">Odds {round.final_odds}</span>}
          {round.stake_cents !== null && <span className="mr-3">Stake {money(round.stake_cents)}</span>}
          {round.payout_cents !== null && <span>Payout {money(round.payout_cents)}</span>}
        </p>
      )}

      <ol className="mt-3 space-y-1.5">
        {round.legs.map((leg, index) => (
          <li key={leg.id} className="flex gap-2 text-sm">
            <span className="w-4 shrink-0 text-right text-xs text-slate-600">{index + 1}</span>
            <span className="text-slate-200">{leg.raw_text}</span>
            <span className="text-xs text-slate-600">&mdash; {leg.member_name}</span>
          </li>
        ))}
        {round.legs.length === 0 && <li className="text-sm text-slate-500">No legs recorded.</li>}
      </ol>

      {canRecord && <ResultForm round={round} leagueId={leagueId} />}
    </Panel>
  );
}

export function HistoryPage() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const league = useLeague(leagueId);
  const history = useRoundHistory(leagueId);

  if (history.isLoading) return <Spinner />;
  if (history.error) return <ErrorNote error={history.error} />;

  const rounds = history.data ?? [];

  return (
    <div className="space-y-5">
      <div>
        <Link to={`/leagues/${leagueId}`} className="text-sm text-slate-400 hover:text-slate-200">
          &lsaquo; {league.data?.name ?? "Back"}
        </Link>
        <h1 className="mt-1 text-2xl font-bold text-white">Past parlays</h1>
      </div>

      {rounds.length === 0 ? (
        <Panel>
          <p className="text-sm text-slate-400">No parlays recorded yet.</p>
        </Panel>
      ) : (
        rounds.map((round) => (
          <RoundCard key={round.id} round={round} leagueId={leagueId!} />
        ))
      )}
    </div>
  );
}
