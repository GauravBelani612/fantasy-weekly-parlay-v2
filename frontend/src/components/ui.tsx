import type { ReactNode } from "react";

import type { Member, RoundStatus } from "../api/types";

export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-[#223047] bg-[#131a26] p-5 shadow-lg shadow-black/20 ${className}`}
    >
      {children}
    </section>
  );
}

export function Button({
  children,
  variant = "primary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger";
}) {
  const styles = {
    primary: "bg-emerald-500 text-slate-950 hover:bg-emerald-400 disabled:bg-slate-700",
    ghost: "border border-[#2d3d57] text-slate-200 hover:bg-[#1b2534] disabled:opacity-40",
    danger: "border border-red-500/40 text-red-300 hover:bg-red-500/10 disabled:opacity-40",
  }[variant];

  return (
    <button
      {...props}
      className={`rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

export function Avatar({ member, size = 32 }: { member: Pick<Member, "display_name" | "avatar_url">; size?: number }) {
  if (member.avatar_url) {
    return (
      <img
        src={member.avatar_url}
        alt=""
        width={size}
        height={size}
        className="shrink-0 rounded-full bg-[#1b2534] object-cover"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full bg-[#243146] text-xs font-bold text-slate-300"
      style={{ width: size, height: size }}
    >
      {member.display_name.slice(0, 2).toUpperCase()}
    </div>
  );
}

const STATUS_STYLES: Record<RoundStatus, string> = {
  open: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  locked: "bg-red-500/15 text-red-300 border-red-500/30",
  upcoming: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

const STATUS_LABEL: Record<RoundStatus, string> = {
  open: "Accepting legs",
  locked: "Locked",
  upcoming: "Not open yet",
};

export function StatusPill({ status }: { status: RoundStatus }) {
  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-semibold ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p className="mt-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
      {message}
    </p>
  );
}

export function Spinner({ label = "Loading..." }: { label?: string }) {
  return <p className="py-8 text-center text-sm text-slate-400">{label}</p>;
}
