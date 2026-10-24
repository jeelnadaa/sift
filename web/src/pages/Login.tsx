import { useState, type FormEvent } from "react";
import { Logo } from "../Logo";
import { post, session } from "../api";
import { errorText } from "../components";

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState(session.email() ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ token: string; user: { email: string } }>("/auth/login", { email: email.trim(), password });
      session.save(r.token, r.user.email);
      onSignedIn();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
      setPassword("");
    }
  }

  return (
    <div className="login">
      <form className="card stack" onSubmit={submit}>
        <Logo size={34} />
        <div className="field"><label htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
        <div className="field"><label htmlFor="pw">Password</label>
          <input id="pw" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
        {error && <p className="err-text" role="alert">{error}</p>}
        <button className="btn btn-primary" disabled={busy} style={{ justifyContent: "center" }}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="dim" style={{ fontSize: 13 }}>Same account as the Sift app on your phone.</p>
      </form>
    </div>
  );
}
