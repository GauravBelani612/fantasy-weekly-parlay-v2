import { Link, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { useLogout, useMe } from "./api/hooks";
import { Spinner } from "./components/ui";
import { HistoryPage } from "./pages/HistoryPage";
import { LeagueHome } from "./pages/LeagueHome";
import { LeaguesPage } from "./pages/LeaguesPage";
import { LegalLinks, Privacy, Terms } from "./pages/Legal";
import { Login } from "./pages/Login";
import { SettingsPage } from "./pages/SettingsPage";
import { StatsPage } from "./pages/StatsPage";

function Header() {
  const me = useMe();
  const logout = useLogout();

  return (
    <header className="border-b border-edge">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
        {/* Echoes the logo's own wordmark treatment. The full mark is a square
            containing this same wordmark, which would be illegible at header size. */}
        <Link to="/" className="text-base font-extrabold tracking-tight">
          <span className="text-white">Weekly</span>
          <span className="text-emerald-400">Lay</span>
        </Link>
        {me.data && (
          <div className="flex items-center gap-3">
            <span className="hidden text-xs text-slate-500 sm:inline">{me.data.user.email}</span>
            <button
              onClick={() => logout.mutate()}
              className="text-xs font-semibold text-slate-400 transition hover:text-slate-200"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

/** Signed-in shell. Renders the login screen in place when there is no session,
 *  so every authenticated route shares one gate. */
function AppLayout() {
  const me = useMe();

  if (me.isLoading) return <Spinner label="Loading..." />;
  if (!me.data) return <Login />;

  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto w-full max-w-3xl px-4 pb-8">
        <LegalLinks />
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      {/* Public on purpose. Google will not let the OAuth consent screen be published
          unless the privacy policy is reachable without signing in, and gating it behind
          the session would have served the login page to anyone following the link. */}
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/terms" element={<Terms />} />

      <Route element={<AppLayout />}>
        <Route path="/" element={<LeaguesPage />} />
        <Route path="/leagues/:leagueId" element={<LeagueHome />} />
        <Route path="/leagues/:leagueId/history" element={<HistoryPage />} />
        <Route path="/leagues/:leagueId/stats" element={<StatsPage />} />
        <Route path="/leagues/:leagueId/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
