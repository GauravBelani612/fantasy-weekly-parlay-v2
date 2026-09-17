import { useEffect, useState } from "react";

function format(msRemaining: number): string {
  if (msRemaining <= 0) return "closed";

  const totalMinutes = Math.floor(msRemaining / 60_000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  const seconds = Math.floor((msRemaining % 60_000) / 1000);

  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function useCountdown(target: string) {
  const targetMs = new Date(target).getTime();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const remaining = targetMs - now;
  return { remaining, expired: remaining <= 0, text: format(remaining) };
}

/** An absolute time, in the reader's own timezone: "Sat, Sep 20, 1:00 PM EDT". */
export function formatDeadline(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** Shorter, for a kickoff inside a sentence: "Sun 1:00 PM". The week is implied. */
export function formatKickoff(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function Countdown({ target, className = "" }: { target: string; className?: string }) {
  const { text, expired, remaining } = useCountdown(target);
  // Under an hour is when people actually need to hurry.
  const urgent = !expired && remaining < 3_600_000;

  return (
    <span
      className={`font-mono tabular-nums ${urgent ? "text-amber-300" : expired ? "text-red-300" : "text-slate-200"} ${className}`}
    >
      {text}
    </span>
  );
}
