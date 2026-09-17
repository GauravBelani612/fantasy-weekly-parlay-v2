import { useState } from "react";

import { useSettleLeg } from "../api/hooks";
import type { Leg, LegResult, RoundOutcome } from "../api/types";
import { Avatar, Button, ErrorNote } from "./ui";

const RESULT_STYLES: Partial<Record<LegResult, [label: string, className: string]>> = {
  hit: ["Hit", "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"],
  miss: ["Miss", "border-red-500/40 bg-red-500/15 text-red-300"],
  void: ["Void", "border-slate-500/40 bg-slate-500/15 text-slate-300"],
  needs_line: ["Needs line", "border-amber-500/40 bg-amber-500/10 text-amber-200"],
  unresolved: ["Check", "border-amber-500/40 bg-amber-500/10 text-amber-200"],
};

export function LegResultBadge({ result }: { result: LegResult }) {
  const style = RESULT_STYLES[result];
  // Pending shows nothing: most legs sit there all week, and a badge on each is noise.
  if (!style) return null;
  const [label, className] = style;
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${className}`}>
      {label}
    </span>
  );
}

const OUTCOME_STYLES: Partial<Record<RoundOutcome, [label: string, className: string]>> = {
  won: ["Cashed", "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"],
  lost: ["Busted", "border-red-500/40 bg-red-500/15 text-red-300"],
  void: ["Voided", "border-slate-500/40 bg-slate-500/15 text-slate-300"],
};

export function OutcomePill({ outcome }: { outcome: RoundOutcome }) {
  const style = OUTCOME_STYLES[outcome];
  if (!style) return null;
  const [label, className] = style;
  return (
    <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${className}`}>
      {label}
    </span>
  );
}

const MANUAL: { result: "hit" | "miss" | "void"; label: string; className: string }[] = [
  { result: "hit", label: "Hit", className: "hover:border-emerald-500/60 hover:text-emerald-300" },
  { result: "miss", label: "Miss", className: "hover:border-red-500/60 hover:text-red-300" },
  { result: "void", label: "Void", className: "hover:border-slate-400 hover:text-slate-200" },
];

function SettleControls({
  leg,
  leagueId,
  roundId,
  onDone,
}: {
  leg: Leg;
  leagueId: string;
  roundId: string;
  onDone: () => void;
}) {
  const settle = useSettleLeg(leagueId, roundId);
  const [line, setLine] = useState(leg.payer_line?.toString() ?? "");
  const parsedLine = Number(line);
  const lineValid = line.trim() !== "" && Number.isFinite(parsedLine);

  const send = (body: Parameters<typeof settle.mutate>[0]) =>
    settle.mutate(body, { onSuccess: onDone });

  // A leg with no line gets both ways out, since either may be easier in the moment:
  // type the number off the bet slip and let it grade itself, or just say how it went.
  const buttons = leg.needs_line ? MANUAL.slice(0, 2) : MANUAL;

  return (
    <div className="mt-3 space-y-2.5 border-t border-edge pt-3">
      {leg.needs_line ? (
        <p className="text-xs text-slate-400">
          No line was written down. Enter the line you placed and this grades itself when the
          game ends &mdash; or just mark how it went.
        </p>
      ) : leg.result === "unresolved" ? (
        <p className="text-xs text-slate-400">
          This couldn&apos;t be settled automatically. Mark how it went &mdash; void only if the
          player didn&apos;t play.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {leg.needs_line && (
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (lineValid) send({ legId: leg.id, line: parsedLine });
            }}
          >
            <input
              value={line}
              onChange={(event) => setLine(event.target.value)}
              inputMode="decimal"
              placeholder="224.5"
              aria-label={`Line placed for ${leg.raw_text}`}
              className="w-24 rounded-lg border border-edge-strong bg-input px-2.5 py-1.5 text-sm text-slate-100 outline-none focus:border-emerald-500"
            />
            <Button type="submit" variant="ghost" disabled={settle.isPending || !lineValid}>
              Save line
            </Button>
            <span className="text-xs text-slate-600">or</span>
          </form>
        )}

        {buttons.map(({ result, label, className }) => (
          <button
            key={result}
            type="button"
            disabled={settle.isPending}
            onClick={() => send({ legId: leg.id, result })}
            className={`rounded-lg border border-edge-strong px-3 py-1.5 text-xs font-semibold text-slate-300 transition disabled:opacity-40 ${
              leg.result === result && leg.graded_by === "manual"
                ? "border-slate-400 text-white"
                : ""
            } ${className}`}
          >
            {label}
          </button>
        ))}

        {leg.graded_by === "manual" && (
          <button
            type="button"
            disabled={settle.isPending}
            onClick={() => send({ legId: leg.id, result: "pending" })}
            className="rounded-lg border border-edge-strong px-3 py-1.5 text-xs font-semibold text-slate-400 transition hover:border-slate-400 hover:text-slate-200 disabled:opacity-40"
          >
            Back to automatic
          </button>
        )}
      </div>

      <ErrorNote error={settle.error} />
    </div>
  );
}

export function LegRow({
  leg,
  index,
  leagueId,
  roundId,
  canSettle,
}: {
  leg: Leg;
  index: number;
  leagueId: string;
  roundId: string;
  /** The payer or the commissioner. */
  canSettle: boolean;
}) {
  // Collapsed by default: the leg and who placed it are what people scan the board for.
  // How it was read and why it got its result are one click away.
  const [expanded, setExpanded] = useState(false);
  const [changing, setChanging] = useState(false);

  // A leg that can't settle without a person shows its controls as soon as it opens.
  // Anything else keeps them behind "Change result", so opening a leg just to see how it
  // was read doesn't also lay out a row of buttons.
  const needsPerson = leg.needs_line || leg.result === "unresolved";
  const detail = leg.result !== "needs_line" ? leg.grade_detail : null;
  const expandable = Boolean(leg.read_as || detail || canSettle);
  const detailsId = `leg-${leg.id}-details`;

  const toggle = () => {
    if (!expandable) return;
    setExpanded((value) => !value);
    setChanging(false);
  };

  const tone =
    leg.result === "hit"
      ? "border-emerald-500/30 bg-emerald-500/5"
      : leg.result === "miss"
        ? "border-red-500/30 bg-red-500/5"
        : leg.is_you
          ? "border-emerald-500/40 bg-emerald-500/5"
          : "border-edge bg-input";

  return (
    <li className={`rounded-lg border ${tone}`}>
      {/* A div rather than a <button>: it holds the avatar and stacked lines, which a
          button may not legally contain. Role, tab stop and keys make it act as one. */}
      <div
        role={expandable ? "button" : undefined}
        tabIndex={expandable ? 0 : undefined}
        aria-expanded={expandable ? expanded : undefined}
        aria-controls={expandable ? detailsId : undefined}
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
          }
        }}
        className={`flex items-start gap-3 rounded-lg px-3 py-2.5 outline-none ${
          expandable
            ? "cursor-pointer transition hover:bg-white/[0.03] focus-visible:ring-2 focus-visible:ring-emerald-500/60"
            : ""
        }`}
      >
        <span className="mt-0.5 w-4 shrink-0 text-right text-xs text-slate-600">{index + 1}</span>
        <Avatar
          member={{ display_name: leg.member_name, avatar_url: leg.member_avatar_url }}
          size={28}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-slate-100">{leg.raw_text}</p>
          <p className="text-xs text-slate-500">{leg.member_name}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2 self-center">
          <LegResultBadge result={leg.result} />
          {expandable && (
            <svg
              aria-hidden="true"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className={`h-4 w-4 text-slate-500 motion-safe:transition-transform ${
                expanded ? "rotate-180" : ""
              }`}
            >
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      </div>

      {expanded && (
        // Indented to sit under the leg text: 0.75rem padding + 1rem number + 0.75rem gap
        // + 1.75rem avatar + 0.75rem gap.
        <div id={detailsId} className="pr-3 pb-3 pl-20">
          {leg.read_as && (
            <p className="text-xs text-slate-500">
              Read as <span className="text-slate-300">{leg.read_as}</span>
            </p>
          )}
          {detail && <p className="mt-0.5 text-xs text-slate-400">{detail}</p>}

          {canSettle &&
            (needsPerson || changing ? (
              <SettleControls
                leg={leg}
                leagueId={leagueId}
                roundId={roundId}
                onDone={() => {
                  setChanging(false);
                  setExpanded(false);
                }}
              />
            ) : (
              <button
                type="button"
                onClick={() => setChanging(true)}
                className="mt-2.5 rounded-lg border border-edge-strong px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:border-slate-400 hover:text-white"
              >
                {leg.result === "pending" ? "Settle by hand" : "Change result"}
              </button>
            ))}
        </div>
      )}
    </li>
  );
}
