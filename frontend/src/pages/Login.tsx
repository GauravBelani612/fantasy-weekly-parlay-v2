import { GoogleSignIn } from "../components/GoogleSignIn";
import { ErrorNote, Panel } from "../components/ui";
import { useGoogleLogin } from "../api/hooks";

export function Login() {
  const login = useGoogleLogin();

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4">
      <h1 className="mb-4">
        <img
          src="/weeklylay-logo.png"
          alt="WeeklyLay"
          width={176}
          height={176}
          className="logo-blend mx-auto h-44 w-44"
        />
      </h1>
      <p className="mb-6 text-center text-sm text-slate-400">
        Your league&apos;s low scorer funds the parlay. Everyone throws in a leg. This app works
        out who lost, collects the legs, and shows the whole board before kickoff.
      </p>

      <Panel>
        <p className="mb-4 text-sm font-semibold text-slate-200">Sign in to continue</p>
        <GoogleSignIn onCredential={(credential) => login.mutate(credential)} />
        {login.isPending && <p className="mt-3 text-sm text-slate-400">Signing you in...</p>}
        <ErrorNote error={login.error} />
      </Panel>
    </div>
  );
}
