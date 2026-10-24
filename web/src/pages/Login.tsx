import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../Logo";
import { get, post, session } from "../api";
import { errorText } from "../components";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState(session.email() ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [canRegister, setCanRegister] = useState(false);
  const [registering, setRegistering] = useState(() => new URLSearchParams(location.search).get("register") === "1");
  const [confirm, setConfirm] = useState("");
  useEffect(() => {
    get<{ registration: boolean }>("/auth/options").then((o) => { setCanRegister(o.registration); if (!o.registration) setRegistering(false); }).catch(() => {});
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (registering && password !== confirm) { setError("The two passwords don't match"); return; }
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ token: string; user: { email: string } }>(registering ? "/auth/register" : "/auth/login", { email: email.trim(), password });
      session.save(r.token, r.user.email);
      onSignedIn();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
      setPassword("");
      setConfirm("");
    }
  }

  return (
    <div className="login">
      <form className="card stack" onSubmit={submit}>
        <Logo size={34} />
        <div className="field"><label htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
        <div className="field"><label htmlFor="pw">Password</label>
          <input id="pw" className="input" type="password" autoComplete={registering ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} required minLength={registering ? 10 : undefined} /></div>
        {registering && (
          <div className="field"><label htmlFor="pw2">Password again</label>
            <input id="pw2" className="input" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required /></div>
        )}
        {registering && <p className="dim" style={{ fontSize: 13 }}>At least 10 characters. You'll connect Gmail after this.</p>}
        {error && <p className="err-text" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy} style={{ justifyContent: "center" }}>
          {busy ? (registering ? "Creating your account…" : "Signing in…") : registering ? "Create account" : "Sign in"}
        </button>
        {canRegister && (
          <button type="button" className="btn btn-ghost" style={{ justifyContent: "center" }} onClick={() => { setRegistering((r) => !r); setError(null); }}>
            {registering ? "I already have an account" : "Create an account"}
          </button>
        )}
        <p className="dim" style={{ fontSize: 13 }}>Same account as the Sift app on your phone. <Link className="link dim" to="/welcome">What is Sift?</Link></p>
      </form>
    </div>
  );
}
