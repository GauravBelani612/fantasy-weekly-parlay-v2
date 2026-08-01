import { Link, Navigate, Route, Routes } from "react-router-dom";

import { useLogout, useMe } from "./api/hooks";
import { Spinner } from "./components/ui";
import { HistoryPage } from "./pages/HistoryPage";
import { LeagueHome } from "./pages/LeagueHome";
import { LeaguesPage } from "./pages/LeaguesPage";
import { Login } from "./pages/Login";
import { SettingsPage } from "./pages/SettingsPage";

function Header() {
  const me = useMe();
  const logout = useLogout();

  return (
    <header className="border-b border-[#223047]">
      <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
        <Link to="/" className="text-sm font-bold tracking-tight text-white">
          Weekly Parlay
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

export default function App() {
  const me = useMe();

  if (me.isLoading) return <Spinner label="Loading..." />;
  if (!me.data) return <Login />;

  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-3xl px-4 py-6">
        <Routes>
          <Route path="/" element={<LeaguesPage />} />
          <Route path="/leagues/:leagueId" element={<LeagueHome />} />
          <Route path="/leagues/:leagueId/history" element={<HistoryPage />} />
          <Route path="/leagues/:leagueId/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
