import { Link } from "react-router-dom";

/** Where privacy questions and deletion requests go.
 *  Must be an address that actually receives mail -- Cloudflare Email Routing
 *  forwards this to a real inbox for free. */
const CONTACT = "privacy@weeklylay.com";
const UPDATED = "September 2026";

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <Link to="/" className="text-sm text-slate-400 transition hover:text-slate-200">
        &lsaquo; WeeklyLay
      </Link>
      <h1 className="mt-3 mb-1 text-2xl font-bold text-white">{title}</h1>
      <p className="mb-8 text-xs text-slate-500">Last updated {UPDATED}</p>
      <div className="space-y-6 text-sm leading-relaxed text-slate-300">{children}</div>
      <p className="mt-10 border-t border-edge pt-5 text-xs text-slate-500">
        Questions? <a className="text-emerald-400 hover:underline" href={`mailto:${CONTACT}`}>{CONTACT}</a>
      </p>
    </div>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-2 text-base font-semibold text-white">{children}</h2>;
}

export function Privacy() {
  return (
    <Shell title="Privacy Policy">
      <p>
        WeeklyLay is a small tool for private fantasy football leagues. It works out which
        manager scored lowest each week, collects one parlay leg from each member, and shows
        the board before kickoff. This policy describes exactly what it stores and why.
      </p>

      <section>
        <H>What we collect</H>
        <ul className="list-disc space-y-1.5 pl-5">
          <li>
            <strong className="text-slate-100">From Google Sign-In:</strong> your email
            address, name, profile picture, and Google account identifier. We never see or
            receive your Google password.
          </li>
          <li>
            <strong className="text-slate-100">From Sleeper, when you link it:</strong> your
            Sleeper username, display name, account id, and avatar, plus the leagues, rosters,
            and weekly scores for leagues added to this app.
          </li>
          <li>
            <strong className="text-slate-100">What you type:</strong> the text of the parlay
            leg you submit, stored exactly as written.
          </li>
        </ul>
        <p className="mt-2">
          There is no analytics, advertising, or third-party tracking of any kind on this site.
        </p>
      </section>

      <section>
        <H>How it is used</H>
        <p>
          Only to run the app: to sign you in and keep you signed in, to identify which roster
          is yours, to calculate each week&apos;s lowest scorer, to display the parlay board to
          your league, and to send the notifications described below. Your information is never
          sold, rented, or used for advertising.
        </p>
      </section>

      <section>
        <H>What other people can see</H>
        <p>
          Other members of a league you join can see your display name, avatar, team name, your
          weekly score, and the text of any leg you submit. That is the point of the app. People
          outside your league cannot see any of it.
        </p>
      </section>

      <section>
        <H>Notifications</H>
        <p>
          The app emails members of your league when a round opens, when a leg is still missing
          near the deadline, and when the parlay locks. If your league commissioner configures a
          Discord or Slack webhook, the same announcements are posted to that channel.
        </p>
      </section>

      <section>
        <H>Services we rely on</H>
        <p>
          Running this app means data passes through a handful of providers, each handling only
          what it needs: <strong className="text-slate-100">Google</strong> for sign-in,{" "}
          <strong className="text-slate-100">Sleeper</strong> for league and score data,{" "}
          <strong className="text-slate-100">ESPN</strong> for kickoff times,{" "}
          <strong className="text-slate-100">Resend</strong> for email delivery, and{" "}
          <strong className="text-slate-100">Neon</strong>,{" "}
          <strong className="text-slate-100">Render</strong>, and{" "}
          <strong className="text-slate-100">Vercel</strong> for the database and hosting.
        </p>
      </section>

      <section>
        <H>Cookies</H>
        <p>
          One cookie, which holds your signed-in session, is set when you sign in and expires
          after 30 days. It cannot be read by JavaScript. There are no advertising or tracking
          cookies.
        </p>
      </section>

      <section>
        <H>Keeping and deleting your data</H>
        <p>
          Your information is kept while your account exists. Email{" "}
          <a className="text-emerald-400 hover:underline" href={`mailto:${CONTACT}`}>{CONTACT}</a>{" "}
          to have your account and associated data deleted, and it will be removed. You can
          unlink your Sleeper account at any time from the app itself.
        </p>
      </section>

      <section>
        <H>Children</H>
        <p>This app is not intended for anyone under 13, and we do not knowingly collect their data.</p>
      </section>

      <section>
        <H>Changes</H>
        <p>
          If this policy changes materially, the date above will be updated. Continuing to use
          the app after a change means you accept it.
        </p>
      </section>
    </Shell>
  );
}

export function Terms() {
  return (
    <Shell title="Terms of Service">
      <section>
        <H>What this is</H>
        <p>
          WeeklyLay is a free hobby project for private fantasy football leagues. It is provided
          as-is, with no warranty, uptime guarantee, or promise that your data will not be lost.
          Do not rely on it for anything that matters.
        </p>
      </section>

      <section>
        <H>It does not handle betting or money</H>
        <p>
          This app records text that league members type. It does not place wagers, connect to
          any sportsbook, process payments, or hold funds. Anything you or your league choose to
          do with the list it produces is entirely your own responsibility, including complying
          with the gambling laws where you live. You must be of legal age to gamble in your
          jurisdiction to do so.
        </p>
      </section>

      <section>
        <H>Your account</H>
        <p>
          You are responsible for activity under your account. Linking a Sleeper account is
          trust-based, since Sleeper offers no way to verify ownership to third parties: do not
          claim a Sleeper account that is not yours. Do not submit content that is unlawful,
          harassing, or infringing.
        </p>
      </section>

      <section>
        <H>Availability</H>
        <p>
          The app runs on free hosting tiers and may be slow, unavailable, or discontinued at any
          time without notice. Accounts that abuse the service may be removed.
        </p>
      </section>

      <section>
        <H>Third parties</H>
        <p>
          Sleeper, ESPN, Google, and the NFL are not affiliated with this app and do not endorse
          it. Their data is used under their own terms.
        </p>
      </section>
    </Shell>
  );
}

/** Footer links. Also surfaced on the signed-out login screen, since that is the page
 *  Google treats as the app's home page. */
export function LegalLinks({ className = "" }: { className?: string }) {
  return (
    <p className={`text-center text-xs text-slate-600 ${className}`}>
      <Link to="/privacy" className="transition hover:text-slate-400">
        Privacy
      </Link>
      <span className="mx-2">&middot;</span>
      <Link to="/terms" className="transition hover:text-slate-400">
        Terms
      </Link>
    </p>
  );
}
