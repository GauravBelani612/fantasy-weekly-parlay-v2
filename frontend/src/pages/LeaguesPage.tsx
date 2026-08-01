import { useState } from "react";
import { Link } from "react-router-dom";

import {
  useClaimSleeper,
  useImportLeague,
  useImportableLeagues,
  useMe,
  useMyLeagues,
} from "../api/hooks";
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
          className="flex-1 rounded-lg border border-[#2d3d57] bg-[#0e141f] px-3 py-2 text-sm text-slate-100 outline-none focus:border-emerald-500"
        />
        <Button type="submit" disabled={claim.isPending || !username.trim()}>
          {claim.isPending ? "Checking..." : "Link"}
        </Button>
      </form>
      <ErrorNote error={claim.error} />
    </Panel>
  );
}

function ImportLeagues({ season }: { season?: string }) {
  const importable = useImportableLeagues(season, true);
  const importLeague = useImportLeague();

  if (importable.isLoading) return <Spinner label="Looking up your Sleeper leagues..." />;
  if (importable.error) return <ErrorNote error={importable.error} />;

  const available = importable.data ?? [];
  if (available.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No Sleeper leagues found for that account this season.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {available.map((league) => (
        <li
          key={league.sleeper_league_id}
          className="flex items-center gap-3 rounded-lg border border-[#223047] bg-[#0e141f] px-3 py-2"
        >
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
              disabled={importLeague.isPending}
              onClick={() => importLeague.mutate(league.sleeper_league_id)}
            >
              Add
            </Button>
          )}
        </li>
      ))}
      <ErrorNote error={importLeague.error} />
    </ul>
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
              <li key={league.id}>
                <Link
                  to={`/leagues/${league.id}`}
                  className="flex items-center gap-3 rounded-lg border border-[#223047] bg-[#0e141f] px-3 py-3 transition hover:border-emerald-500/50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-slate-100">{league.name}</p>
                    <p className="text-xs text-slate-500">
                      {league.season} &middot; {league.total_rosters} teams
                      {league.your_role === "commissioner" && " &middot; commissioner"}
                    </p>
                  </div>
                  <span className="text-slate-500">&rsaquo;</span>
                </Link>
              </li>
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
