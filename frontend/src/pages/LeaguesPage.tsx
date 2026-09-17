import { useState } from "react";
import { Link } from "react-router-dom";

import {
  useClaimSleeper,
  useDeleteLeague,
  useImportLeague,
  useImportableLeagues,
  useMe,
  useMyLeagues,
} from "../api/hooks";
import type { League, SleeperLeague } from "../api/types";
import { Button, ErrorNote, Panel, Spinner } from "../components/ui";

function LinkSleeperCard() {
  const [username, setUsername] = useState("");
  const claim = useClaimSleeper();

  return (
    <Panel>
      <h2 className="text-lg font-semibold text-white">Link your Sleeper account</h2>
      <p className="mt-1 mb-4 text-sm text-slate-400">
        Enter the username you log into Sleeper with. Sleeper has no official sign-in for other
        apps, so this is claim-based &mdash; once an account is linked here, nobody else can take
        it.
      </p>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (username.trim()) claim.mutate(username.trim());
        }}
      >
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          placeholder="sleeper username"
          autoComplete="off"
          className="flex-1 rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
        />
        <Button type="submit" disabled={claim.isPending || !username.trim()}>
          {claim.isPending ? "Checking..." : "Link"}
        </Button>
      </form>
      <ErrorNote error={claim.error} />
    </Panel>
  );
}

function ImportRow({
  league,
  onAdd,
  pending,
}: {
  league: SleeperLeague;
  onAdd: (id: string) => void;
  pending: boolean;
}) {
  return (
    <li className="flex items-center gap-3 rounded-lg border border-edge bg-input px-3 py-2">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-slate-100">{league.name}</p>
        <p className="text-xs text-slate-500">
          {league.season} &middot; {league.total_rosters} teams
        </p>
      </div>
      {league.already_imported ? (
        <span className="text-xs font-semibold text-emerald-400">Added</span>
      ) : (
        <Button
          variant="ghost"
          disabled={pending}
          onClick={() => onAdd(league.sleeper_league_id)}
        >
          Add
        </Button>
      )}
    </li>
  );
}

function ImportLeagues({ season }: { season?: string }) {
  const importable = useImportableLeagues(season, true);
  const importLeague = useImportLeague();

  if (importable.isLoading) return <Spinner label="Looking up your Sleeper leagues..." />;
  if (importable.error) return <ErrorNote error={importable.error} />;

  const available = importable.data ?? [];
  // A league nobody finished configuring in Sleeper is almost always an abandoned twin
  // of a real one. Adding it would give the league a second parlay every week, with its
  // own payer and its own emails, so it is never offered -- not even behind a reveal.
  const real = available.filter((l) => !l.unconfigured);

  if (available.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No Sleeper leagues found for that account this season.
      </p>
    );
  }

  return (
    <>
      {real.length === 0 ? (
        <p className="text-sm text-slate-400">
          Nothing here looks like a finished league &mdash; every one is missing its playoff
          settings.
        </p>
      ) : (
        <ul className="space-y-2">
          {real.map((league) => (
            <ImportRow
              key={league.sleeper_league_id}
              league={league}
              onAdd={(id) => importLeague.mutate(id)}
              pending={importLeague.isPending}
            />
          ))}
        </ul>
      )}

      <ErrorNote error={importLeague.error} />
    </>
  );
}

function LeagueRow({ league }: { league: League }) {
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteLeague();
  const isCommissioner = league.your_role === "commissioner";

  return (
    <li className="rounded-lg border border-edge bg-input transition hover:border-emerald-500/50">
      <div className="flex items-center gap-3 px-3 py-3">
        {/* The remove button is a sibling of the link, never inside it -- a button nested
            in an anchor is invalid markup and swallows the click on some browsers. */}
        <Link to={`/leagues/${league.id}`} className="flex min-w-0 flex-1 items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-slate-100">{league.name}</p>
            <p className="text-xs text-slate-500">
              {league.season} &middot; {league.total_rosters} teams
              {isCommissioner && " · commissioner"}
            </p>
          </div>
          <span className="text-slate-500">&rsaquo;</span>
        </Link>
        {isCommissioner && !confirming && (
          <button
            onClick={() => setConfirming(true)}
            className="shrink-0 rounded-lg border border-edge-strong px-2.5 py-1 text-xs font-semibold text-slate-400 transition hover:border-red-500/40 hover:text-red-300"
          >
            Remove
          </button>
        )}
      </div>

      {confirming && (
        <div className="border-t border-edge px-3 py-3">
          <p className="text-xs text-slate-400">
            Remove <span className="font-semibold text-slate-200">{league.name}</span> for
            everyone in it? Submitted legs and past parlays go with it. Your Sleeper league is
            untouched, so you can add it again at any time.
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => remove.mutate(league.id)}
            >
              {remove.isPending ? "Removing..." : "Yes, remove it"}
            </Button>
            <Button variant="ghost" disabled={remove.isPending} onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
          <ErrorNote error={remove.error} />
        </div>
      )}
    </li>
  );
}

export function LeaguesPage() {
  const me = useMe();
  const leagues = useMyLeagues();

  if (me.isLoading) return <Spinner />;
  if (!me.data?.sleeper) return <LinkSleeperCard />;

  return (
    <div className="space-y-6">
      <Panel>
        <h2 className="mb-3 text-lg font-semibold text-white">Your leagues</h2>
        {leagues.isLoading ? (
          <Spinner />
        ) : (leagues.data?.length ?? 0) === 0 ? (
          <p className="text-sm text-slate-400">
            Nothing yet &mdash; add one of your Sleeper leagues below.
          </p>
        ) : (
          <ul className="space-y-2">
            {leagues.data!.map((league) => (
              <LeagueRow key={league.id} league={league} />
            ))}
          </ul>
        )}
        <ErrorNote error={leagues.error} />
      </Panel>

      <Panel>
        <h2 className="mb-3 text-lg font-semibold text-white">Add a league from Sleeper</h2>
        <ImportLeagues />
      </Panel>
    </div>
  );
}
