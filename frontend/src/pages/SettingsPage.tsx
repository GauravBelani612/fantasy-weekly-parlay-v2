import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useLeague, useSyncLeague, useUpdateSettings } from "../api/hooks";
import type { DeadlineMode } from "../api/types";
import { Avatar, Button, ErrorNote, Panel, Spinner } from "../components/ui";

export function SettingsPage() {
  const { leagueId } = useParams<{ leagueId: string }>();
  const league = useLeague(leagueId);
  const update = useUpdateSettings(leagueId!);
  const sync = useSyncLeague(leagueId!);

  const [mode, setMode] = useState<DeadlineMode | null>(null);
  const [monday, setMonday] = useState<boolean | null>(null);
  const [lockOffset, setLockOffset] = useState<string | null>(null);
  const [firstWeek, setFirstWeek] = useState<string | null>(null);
  const [lastWeek, setLastWeek] = useState<string | null>(null);
  const [webhook, setWebhook] = useState("");

  if (league.isLoading) return <Spinner />;
  if (!league.data) return <ErrorNote error={league.error} />;

  const data = league.data;
  const isCommissioner = data.your_role === "commissioner";

  return (
    <div className="space-y-5">
      <div>
        <Link to={`/leagues/${leagueId}`} className="text-sm text-slate-400 hover:text-slate-200">
          &lsaquo; {data.name}
        </Link>
        <h1 className="mt-1 text-2xl font-bold text-white">League settings</h1>
      </div>

      {isCommissioner && (
        <Panel>
          <h2 className="mb-3 text-lg font-semibold text-white">Parlay rules</h2>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              const payload: Record<string, unknown> = {};
              if (mode !== null) payload.deadline_mode = mode;
              if (monday !== null) payload.allow_monday = monday;
              if (lockOffset !== null) payload.lock_offset_minutes = Number(lockOffset);
              if (firstWeek !== null) payload.first_scored_week = Number(firstWeek);
              if (lastWeek !== null) payload.last_scored_week = Number(lastWeek);
              if (webhook.trim()) payload.discord_webhook_url = webhook.trim();
              update.mutate(payload);
            }}
          >
            <fieldset className="block text-sm text-slate-400">
              <legend>When the week's deadline falls</legend>
              <div className="mt-2 space-y-2">
                {(
                  [
                    ["first_kickoff", "The week's first kickoff", "Usually Thursday night."],
                    [
                      "sunday",
                      "The first Sunday kickoff",
                      "Locks Sunday morning instead, and only takes legs on Sunday and Monday games. A week with an international morning game opens \u2014 and locks \u2014 about three hours earlier than one without.",
                    ],
                  ] as const
                ).map(([value, label, hint]) => (
                  <label key={value} className="flex gap-2.5">
                    <input
                      type="radio"
                      name="deadline_mode"
                      value={value}
                      checked={(mode ?? data.deadline_mode) === value}
                      onChange={() => setMode(value)}
                      className="mt-0.5 accent-emerald-500"
                    />
                    <span>
                      <span className="text-slate-200">{label}</span>
                      <span className="block text-xs text-slate-600">{hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            <label className="block text-sm text-slate-400">
              Lock submissions this many minutes before that kickoff
              <input
                type="number"
                min={0}
                max={10080}
                value={lockOffset ?? data.lock_offset_minutes}
                onChange={(event) => setLockOffset(event.target.value)}
                className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100"
              />
              <span className="mt-1 block text-xs text-slate-600">
                60 means legs close an hour before the game the deadline hangs off.
              </span>
            </label>

            <label className="flex gap-2.5 text-sm text-slate-400">
              <input
                type="checkbox"
                checked={monday ?? data.allow_monday}
                onChange={(event) => setMonday(event.target.checked)}
                className="mt-0.5 accent-emerald-500"
              />
              <span>
                <span className="text-slate-200">Allow Monday night games</span>
                <span className="block text-xs text-slate-600">
                  Off means the week is over on Sunday night, at the cost of one game. It does
                  not move the deadline.
                </span>
              </span>
            </label>

            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm text-slate-400">
                First scored week
                <input
                  type="number"
                  min={1}
                  max={18}
                  value={firstWeek ?? data.first_scored_week}
                  onChange={(event) => setFirstWeek(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100"
                />
              </label>
              <label className="block text-sm text-slate-400">
                Last scored week
                <input
                  type="number"
                  min={1}
                  max={18}
                  value={lastWeek ?? data.last_scored_week}
                  onChange={(event) => setLastWeek(event.target.value)}
                  className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100"
                />
              </label>
            </div>

            <label className="block text-sm text-slate-400">
              Discord / Slack webhook URL
              <input
                type="url"
                value={webhook}
                onChange={(event) => setWebhook(event.target.value)}
                placeholder={
                  data.has_discord_webhook ? "A webhook is set (hidden)" : "https://discord.com/api/webhooks/..."
                }
                className="mt-1 w-full rounded-lg border border-edge-strong bg-input px-3 py-2 text-sm text-slate-100"
              />
              <span className="mt-1 block text-xs text-slate-600">
                Write-only &mdash; the saved URL is never sent back to the browser.
              </span>
            </label>

            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? "Saving..." : "Save settings"}
            </Button>
            <ErrorNote error={update.error} />
          </form>
        </Panel>
      )}

      <Panel>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Members</h2>
          <Button variant="ghost" disabled={sync.isPending} onClick={() => sync.mutate()}>
            {sync.isPending ? "Syncing..." : "Sync from Sleeper"}
          </Button>
        </div>
        <ul className="space-y-2">
          {data.members.map((member) => (
            <li
              key={member.id}
              className="flex items-center gap-3 rounded-lg border border-edge bg-input px-3 py-2"
            >
              <Avatar member={member} size={30} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-100">
                  {member.display_name}
                  {member.is_you && <span className="ml-2 text-xs text-emerald-400">you</span>}
                </p>
                {member.team_name && (
                  <p className="truncate text-xs text-slate-500">{member.team_name}</p>
                )}
              </div>
              {member.role === "commissioner" && (
                <span className="text-xs text-slate-500">commissioner</span>
              )}
              <span
                className={`text-xs ${member.has_app_account ? "text-emerald-400" : "text-slate-600"}`}
              >
                {member.has_app_account ? "signed up" : "not signed up"}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-slate-600">
          Members who haven&apos;t signed up still count for the low-score calculation, but
          can&apos;t submit a leg.
        </p>
        <ErrorNote error={sync.error} />
      </Panel>
    </div>
  );
}
