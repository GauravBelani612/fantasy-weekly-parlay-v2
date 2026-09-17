import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  useCurrentRound,
  useDeleteLeg,
  useLeague,
  useRefreshRound,
  useSetLoser,
  useSubmitLeg,
} from "../api/hooks";
import type { LeagueDetail, Round } from "../api/types";
import { Countdown, formatDeadline } from "../components/Countdown";
import { LegRow, OutcomePill } from "../components/Legs";
import { Avatar, Button, ErrorNote, Panel, Spinner, StatusPill } from "../components/ui";

function LoserCard({ round, league }: { round: Round; league: LeagueDetail }) {
  const setLoser = useSetLoser(league.id, round.id);
  const [choice, setChoice] = useState("");

  if (round.tie_roster_ids?.length) {
    const tied = league.members.filter((m) =>
      round.tie_roster_ids!.includes(m.sleeper_roster_id),
    );
    const isCommissioner = league.your_role === "commissioner";

    return (
      <Panel className="border-amber-500/40 bg-amber-500/5">
        <h2 className="text-lg font-semibold text-amber-200">
          Week {round.scored_week} ended in a tie
        </h2>
        <p className="mt-1 text-sm text-slate-300">
          {tied.map((m) => m.display_name).join(" and ")} both scored{" "}
          {round.loser_points?.toFixed(2)}. Ties are never broken automatically &mdash; the
          commissioner decides who pays.
        </p>
        {isCommissioner ? (
          <div className="mt-4 flex flex-wrap gap-2">
            <select
              value={choice}
              onChange={(event) => setChoice(event.target.value)}
              className="rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100"
            >
              <option value="">Choose who pays...</option>
              {tied.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name}
                </option>
              ))}
            </select>
            <Button disabled={!choice || setLoser.isPending} onClick={() => setLoser.mutate(choice)}>
              Confirm
            </Button>
          </div>
        ) : (
          <p className="mt-3 text-xs text-slate-400">Waiting on the commissioner to settle it.</p>
        )}
        <ErrorNote error={setLoser.error} />
      </Panel>
    );
  }

  if (!round.loser) {
    return (
      <Panel>
        <p className="text-sm text-slate-400">
          Scores for week {round.scored_week} are not in yet.
        </p>
      </Panel>
    );
  }

  return (
    <Panel>
      <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
        Week {round.scored_week} low scorer &mdash; funds this parlay
      </p>
      <div className="mt-3 flex items-center gap-3">
        <Avatar member={round.loser} size={44} />
        <div className="min-w-0">
          <p className="truncate text-xl font-bold text-white">
            {round.loser.display_name}
            {round.loser.is_you && (
              <span className="ml-2 text-sm font-semibold text-amber-300">that&apos;s you</span>
            )}
          </p>
          <p className="text-sm text-slate-400">
            {round.loser_points?.toFixed(2)} points
            {round.loser.team_name && ` · ${round.loser.team_name}`}
          </p>
        </div>
      </div>
      {!round.loser_has_app_account && (
        <p className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          {round.loser.display_name} hasn&apos;t signed into this app yet, so they won&apos;t get
          the &ldquo;go place the bet&rdquo; email. Send them the link.
        </p>
      )}
    </Panel>
  );
}

function LegForm({ round, leagueId }: { round: Round; leagueId: string }) {
  const submit = useSubmitLeg(leagueId, round.id);
  const remove = useDeleteLeg(leagueId, round.id);
  const [text, setText] = useState(round.your_leg?.raw_text ?? "");

  // Adopt the server value when the round or the saved leg changes underneath us.
  useEffect(() => {
    setText(round.your_leg?.raw_text ?? "");
  }, [round.id, round.your_leg?.raw_text]);

  if (round.status === "locked") {
    return (
      <Panel>
        <h2 className="text-lg font-semibold text-white">Submissions are closed</h2>
        <p className="mt-1 text-sm text-slate-400">
          {round.your_leg
            ? `Your leg: ${round.your_leg.raw_text}`
            : "You didn't get a leg in this week."}
        </p>
      </Panel>
    );
  }

  if (!round.you_can_submit && !round.your_leg) {
    return (
      <Panel>
        <p className="text-sm text-slate-400">
          You don&apos;t hold a roster in this league, so you can&apos;t submit a leg.
        </p>
      </Panel>
    );
  }

  const dirty = text.trim() !== (round.your_leg?.raw_text ?? "");

  return (
    <Panel>
      <h2 className="text-lg font-semibold text-white">
        Your leg for week {round.bet_week}
      </h2>
      <p className="mt-1 mb-3 text-sm text-slate-400">
        Write it however you like &mdash; &ldquo;Ja&apos;Marr Chase over 89.5 rec yds&rdquo;,
        &ldquo;Bills -3.5&rdquo;, &ldquo;Hurts anytime TD&rdquo;. One leg each.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim().length >= 2) submit.mutate(text.trim());
        }}
      >
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={2}
          maxLength={500}
          placeholder="Your bet..."
          className="w-full resize-none rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button type="submit" disabled={submit.isPending || !dirty || text.trim().length < 2}>
            {round.your_leg ? "Update leg" : "Submit leg"}
          </Button>
          {round.your_leg && (
            <Button
              type="button"
              variant="danger"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Remove
            </Button>
          )}
          {round.your_leg && !dirty && (
            <span className="text-xs font-semibold text-emerald-400">Saved</span>
          )}
        </div>
      </form>
      <ErrorNote error={submit.error ?? remove.error} />
    </Panel>
  );
}

function LegBoard({
  round,
  leagueId,
  canSettle,
}: {
  round: Round;
  leagueId: string;
  canSettle: boolean;
}) {
  return (
    <Panel>
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-lg font-semibold text-white">
          The parlay &mdash; week {round.bet_week}
        </h2>
        <span className="text-sm text-slate-400">
          {round.submitted_count} of {round.eligible_count} in
        </span>
      </div>

      {round.legs.length === 0 ? (
        <p className="text-sm text-slate-400">No legs yet. Be the first.</p>
      ) : (
        <ol className="space-y-2">
          {round.legs.map((leg, index) => (
            <LegRow
              key={leg.id}
              leg={leg}
              index={index}
              leagueId={leagueId}
              roundId={round.id}
              canSettle={canSettle}
            />
          ))}
        </ol>
      )}

      {round.awaiting.length > 0 && (
        <div className="mt-4 border-t border-edge pt-3">
          <p className="text-xs font-semibold tracking-wide text-slate-500 uppercase">
            Still waiting on
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {round.awaiting.map((member) => (
              <span
                key={member.id}
                className="flex items-center gap-1.5 rounded-full border border-edge-strong px-2.5 py-1 text-xs text-slate-300"
              >
                <Avatar member={member} size={16} />
                {member.display_name}
              </span>
            ))}
          </div>
        </div>
      )}
    </Panel>
  );
}

export function LeagueHome() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const league = useLeague(leagueId);
  const round = useCurrentRound(leagueId);
  const refresh = useRefreshRound(leagueId!);

  if (league.isLoading || round.isLoading) return <Spinner />;
  if (league.error) return <ErrorNote error={league.error} />;
  if (!league.data) return null;

  const data = round.data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white">{league.data.name}</h1>
          <p className="text-sm text-slate-500">
            {league.data.season} &middot; {league.data.total_rosters} teams
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to={`/leagues/${leagueId}/stats`}
            className="rounded-lg border border-edge-strong px-4 py-2 text-sm font-semibold text-slate-200 transition hover:bg-panel-hover"
          >
            Stats
          </Link>
          <Link
            to={`/leagues/${leagueId}/history`}
            className="rounded-lg border border-edge-strong px-4 py-2 text-sm font-semibold text-slate-200 transition hover:bg-panel-hover"
          >
            History
          </Link>
          {league.data.your_role === "commissioner" && (
            <Link
              to={`/leagues/${leagueId}/settings`}
              className="rounded-lg border border-edge-strong px-4 py-2 text-sm font-semibold text-slate-200 transition hover:bg-panel-hover"
            >
              Settings
            </Link>
          )}
        </div>
      </div>

      {!data ? (
        <Panel>
          <h2 className="text-lg font-semibold text-white">No parlay open yet</h2>
          <p className="mt-1 text-sm text-slate-400">
            The first round opens once week {league.data.first_scored_week} is final &mdash; legs
            are then placed on week {league.data.first_scored_week + 1}&apos;s games.
          </p>
          <Button
            className="mt-4"
            variant="ghost"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate()}
          >
            {refresh.isPending ? "Checking..." : "Check now"}
          </Button>
          <ErrorNote error={refresh.error} />
        </Panel>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill status={data.status} />
            <OutcomePill outcome={data.outcome} />
            <span className="text-sm text-slate-400">
              {data.status === "locked" ? "Locked " : "Locks in "}
              <Countdown target={data.locks_at} />
              <span className="ml-2 text-slate-600">
                ({formatDeadline(data.locks_at)})
              </span>
            </span>
          </div>

          <LoserCard round={data} league={league.data} />
          <LegForm round={data} leagueId={leagueId!} />
          <LegBoard
            round={data}
            leagueId={leagueId!}
            // The payer saw the real sportsbook lines; the commissioner settles disputes.
            canSettle={league.data.your_role === "commissioner" || Boolean(data.loser?.is_you)}
          />
        </>
      )}
    </div>
  );
}
