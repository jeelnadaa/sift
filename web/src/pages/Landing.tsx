/** The public landing page (signed-out visitors), built from design/landing. Everything is
 * bundled (the page's policy allows no inline or third-party scripts); motion stops when the
 * visitor asks for reduced motion. */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { LogoMark, LogoWord } from "../Logo";
import "./landing.css";

const reduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

export function Landing() {
  const [canRegister, setCanRegister] = useState(true);
  useEffect(() => {
    document.title = "Sift · your inbox, sifted";
    get<{ registration: boolean }>("/auth/options").then((o) => setCanRegister(o.registration)).catch(() => {});
  }, []);
  useReveal();
  const start = canRegister ? { to: "/login?register=1", label: "Create your account →" } : { to: "/login", label: "Sign in →" };

  return (
    <div className="landing">
      <nav className="l-nav" aria-label="Sift">
        <div className="l-bar">
          <a className="l-logo" href="#top" aria-label="Sift, top of page"><LogoMark size={26} /><LogoWord height={21} /></a>
          <a className="l-link" href="#how">How it works</a>
          <a className="l-link" href="#features">Features</a>
          <a className="l-link" href="#key">Your key</a>
          <Link className="btn btn-ghost btn-sm" to="/login">Sign in</Link>
          {canRegister && <Link className="btn btn-primary btn-sm" to="/login?register=1">Get started</Link>}
        </div>
      </nav>

      <header className="l-hero" id="top">
        <div className="l-wrap l-hero-grid">
          <Sieve />
          <h1><span className="line"><span>Your inbox,</span></span><span className="line"><span><em>sifted.</em></span></span></h1>
          <p className="l-sub">Sift watches every Gmail account you own, runs your rules first, and buzzes your phone the second something matters. Bank alerts cost nothing. Placement mail lands on one timeline per company.</p>
          <div className="l-cta">
            <Link className="btn btn-primary" to={start.to}>{start.label}</Link>
            <a className="btn btn-ghost" href="#how">See how it works</a>
          </div>
          <div className="l-stats">
            <div><b><Count to={2} /></b><span>seconds, mail to buzz</span></div>
            <div><b><Count to={0} /></b><span>tokens spent on bank alerts</span></div>
            <div><b><Count to={100} suffix="%" /></b><span>your own key, your data</span></div>
          </div>
        </div>
      </header>

      <div className="l-marquee" aria-hidden="true">
        <div className="l-track">
          {[0, 1].map((k) => (
            <span key={k}>
              <i className="hl">Instant push</i><i>Rules first</i><i className="hl">Company timelines</i><i>Multi-account</i>
              <i className="hl">Folders that sort themselves</i><i>Write and send later</i><i className="hl">Bring your own key</i><i>Silent by default</i>
            </span>
          ))}
        </div>
      </div>

      <section id="how" className="l-sec">
        <div className="l-wrap">
          <span className="l-eyebrow rv">The pipeline</span>
          <h2 className="l-big rv" style={{ "--d": 1 } as React.CSSProperties}>Cheap checks first. <em>AI last.</em></h2>
          <p className="l-lead rv" style={{ "--d": 2 } as React.CSSProperties}>Every new mail walks the same short road. Most of it is settled before a single token is spent.</p>
          <div className="l-pipe">
            {[
              ["01", "Arrives", "Gmail tells Sift the moment mail lands, on every account you connect.", "Instant", "ok"],
              ["02", "Your rules", "First match wins: sender, domain, subject, keywords, with exceptions so fraud alerts still get through.", "0 tokens", ""],
              ["03", "Fingerprint", "Seen this exact template before and silenced it? Same call, instantly, for free.", "0 tokens", ""],
              ["04", "Small AI", "Only what's left. One call, personal details hidden, never old mail. Then into the right folder.", "Your key", "urgent"],
            ].map(([n, h, p, tag, tone], i) => (
              <div key={n} className="rv" style={{ "--d": i } as React.CSSProperties}>
                <span className="n">{n}</span><h3>{h}</h3><p>{p}</p><span className={`tag ${tone} tagline`}>{tag}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="features" className="l-sec" style={{ paddingTop: 0 }}>
        <div className="l-wrap">
          <span className="l-eyebrow rv">What you get</span>
          <h2 className="l-big rv" style={{ "--d": 1 } as React.CSSProperties}>Everything about your mail. In one place.</h2>
          <div className="l-bento">
            <div className="card b-a rv">
              <h3>One timeline per company.</h3>
              <p>College announcement, company follow-up, test link: different senders, different accounts, one timeline in order. Add your own steps with a date and time.</p>
              <div className="l-tl">
                <div className="done"><i /><div><b>Announcement · placement cell</b><span>Mon 9:02 · college account</span></div></div>
                <div className="done"><i /><div><b>Registration open · Acme Corp</b><span>Mon 11:40 · deadline Wed 6 PM</span></div></div>
                <div className="done"><i /><div><b>Online test · HirePro</b><span>Tue 8:15 · reminders 24 h and 2 h before</span></div></div>
                <div><i /><div><b className="dim">Interview, round 2</b><span>Added by you · Fri 10:00</span></div></div>
              </div>
            </div>
            <div className="card b-b rv" style={{ "--d": 1 } as React.CSSProperties}>
              <h3>Silent, not lost.</h3>
              <p>Bank noise is kept and searchable, never notified.</p>
              <div className="l-silence">
                <div className="x">UPI debit ₹240 · Kotak</div>
                <div className="x">Card spent ₹1,180 · Slice</div>
                <div className="keep">⚠ Card blocked · Kotak</div>
              </div>
            </div>
            <div className="card b-c rv">
              <h3>Folders that sort themselves.</h3>
              <p>Placement mail files itself into Placements, one subfolder per company. Or tell the AI how to group a folder, and ask it to build timelines or to-dos from what's already there.</p>
              <div className="l-tree"><span>▾ Placements</span><span className="in">Acme Corp</span><span className="in">Globex</span><span className="in dim">+ made as mail arrives</span></div>
            </div>
            <div className="card b-d rv" style={{ "--d": 1 } as React.CSSProperties}>
              <h3>Read, search and write. Without opening Gmail.</h3>
              <p>Whole conversations in Sift's own look. Gmail search plus Sift's filters, or search by meaning. Reply, forward, attach, undo send, send later, and get reminded when nobody answers.</p>
              <div className="l-chips">
                <span className="chip">from:acme newer_than:7d</span><span className="chip">◆ has a deadline</span><span className="chip on">Send later · Mon 9:00</span><span className="chip">Remind me in 3 days</span>
              </div>
            </div>
            <div className="card b-e rv">
              <h3>Every account. One feed.</h3>
              <p>Connect as many Gmail accounts as you like. If one is revoked or blocked, only that one pauses, and you're told.</p>
            </div>
            <div className="card b-f rv" style={{ "--d": 1 } as React.CSSProperties}>
              <span className="l-num">0</span>
              <h3>tokens for noise</h3>
              <p>Rules handle the bulk. A daily cap handles the rest, and the usage page shows where every token went.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="l-phone-sec l-sec" id="mobile">
        <div className="l-wrap l-phone-grid">
          <div>
            <span className="l-eyebrow rv">Android</span>
            <h2 className="l-big rv" style={{ "--d": 1 } as React.CSSProperties}>Buzz. Tap. Done.</h2>
            <p className="l-lead rv" style={{ "--d": 2 } as React.CSSProperties}>Priority channels with their own sound. Actions right in the notification. Urgent mail keeps nagging until you see it. Everything the web does, in your pocket.</p>
          </div>
          <Phone />
        </div>
      </section>

      <section id="key" className="l-sec">
        <div className="l-wrap">
          <span className="l-eyebrow rv">Bring your own key</span>
          <h2 className="l-big rv" style={{ "--d": 1 } as React.CSSProperties}>Your key. Your tokens. <em>Your call.</em></h2>
          <p className="l-lead rv" style={{ "--d": 2 } as React.CSSProperties}>Sift ships with no shared key. Add your own Gemini key and the AI features switch on. Skip it and everything else still works: push, rules, folders, search, writing mail.</p>
          <div className="l-key rv" style={{ "--d": 3 } as React.CSSProperties}><span className="dim">GEMINI_KEY</span><span>••••••••••••••••a91f</span><span className="ok">✓ valid</span></div>
        </div>
      </section>

      <section className="l-final">
        <div className="l-wrap">
          <h2 className="rv">Stop <em>digging.</em><br />Start sifting.</h2>
          <div className="l-final-cta rv">
            <Link className="btn btn-primary" to={start.to}>{start.label}</Link>
            {canRegister && <Link className="btn btn-ghost" to="/login">I already have an account</Link>}
          </div>
        </div>
      </section>

      <footer className="l-foot"><div className="l-wrap"><span>© 2026 Sift · a solarquack project</span><span>Read-only until you ask. Never logs email bodies.</span></div></footer>
    </div>
  );
}

function useReveal() {
  useEffect(() => {
    const els = document.querySelectorAll(".landing .rv");
    if (reduced() || typeof IntersectionObserver === "undefined") { els.forEach((e) => e.classList.add("in")); return; }
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { threshold: 0.15 });
    els.forEach((e) => io.observe(e));
    return () => io.disconnect();
  }, []);
}

function Count({ to, suffix = "" }: { to: number; suffix?: string }) {
  const [n, setN] = useState(reduced() ? to : 0);
  useEffect(() => {
    if (reduced()) return;
    let raf = 0;
    const t0 = performance.now() + 700;
    const tick = (t: number) => {
      const p = Math.min(Math.max((t - t0) / 1200, 0), 1);
      setN(Math.round(to * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return <>{n}{suffix}</>;
}

function Phone() {
  const ref = useRef<HTMLDivElement>(null);
  const [go, setGo] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduced() || typeof IntersectionObserver === "undefined") { setGo(true); return; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setGo(true); io.disconnect(); } }, { threshold: 0.3 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className={`l-phone ${go ? "go" : ""}`} aria-hidden="true">
      <div className="notch" />
      <div className="push"><div className="h"><span className="dot urgent" /><b>SIFT · URGENT</b> · now</div><div className="t">HirePro test · Acme Corp</div><div className="s">Test link live, closes tonight 11:59 PM</div><div className="acts"><span className="p">Open link</span><span>Add to-do</span></div></div>
      <div className="push"><div className="h"><span className="dot normal" /><b>SIFT · NORMAL</b> · now</div><div className="t">Which company is this?</div><div className="s">New mail from hr@globex-careers.in</div><div className="acts"><span className="p">Acme</span><span>Globex</span><span>New</span></div></div>
      <div className="push"><div className="h"><span className="dot digest" /><b>SIFT · DIGEST</b> · now</div><div className="t">No reply yet</div><div className="s">“Offer letter” to hr@acme.com, sent 3 days ago</div></div>
    </div>
  );
}

/** Mail falls; noise stops at the mesh, what matters passes through and lights up. */
function Sieve() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    const x = c?.getContext("2d");
    if (!c || !x || reduced()) return;
    let w = 0, h = 0, raf = 0, last = 0;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const fit = () => { w = c.clientWidth; h = c.clientHeight; c.width = w * dpr; c.height = h * dpr; x.setTransform(dpr, 0, 0, dpr, 0, 0); };
    fit();
    addEventListener("resize", fit);
    const items: { x: number; y: number; vy: number; w: number; sig: boolean; o: number; dead: boolean; r: number }[] = [];
    const frame = (t: number) => {
      x.clearRect(0, 0, w, h);
      if (t - last > 380) { items.push({ x: w * (0.15 + Math.random() * 0.7), y: -30, vy: 1 + Math.random() * 1.4, w: 46 + Math.random() * 40, sig: Math.random() < 0.14, o: 0, dead: false, r: (Math.random() - 0.5) * 0.5 }); last = t; }
      const mesh = h * 0.55;
      x.strokeStyle = "rgba(244,243,238,.18)"; x.lineWidth = 1;
      for (let i = 0; i < 28; i++) { const px = (w / 28) * i; x.beginPath(); x.moveTo(px, mesh - 6); x.lineTo(px, mesh + 6); x.stroke(); }
      x.beginPath(); x.moveTo(0, mesh); x.lineTo(w, mesh); x.stroke();
      for (let i = items.length - 1; i >= 0; i--) {
        const m = items[i];
        m.y += m.vy; m.o = Math.min(m.o + 0.04, 1);
        if (!m.sig && m.y > mesh - 10) m.dead = true;
        if (m.dead) { m.o -= 0.08; m.y -= 0.6; if (m.o <= 0) { items.splice(i, 1); continue; } }
        if (m.y > h + 40) { items.splice(i, 1); continue; }
        const lit = m.sig && m.y > mesh;
        x.save(); x.globalAlpha = Math.max(m.o, 0); x.translate(m.x, m.y); x.rotate(m.r);
        x.fillStyle = lit ? "#c8ff3d" : "#1c1c20"; x.strokeStyle = m.sig ? "#c8ff3d" : "#34343b";
        if (lit) { x.shadowColor = "#c8ff3d"; x.shadowBlur = 24; }
        x.beginPath();
        if (x.roundRect) x.roundRect(-m.w / 2, -14, m.w, 28, 4); else x.rect(-m.w / 2, -14, m.w, 28);
        x.fill(); x.stroke();
        x.shadowBlur = 0; x.fillStyle = lit ? "#10150a" : "#5b5b64";
        x.fillRect(-m.w / 2 + 9, -3, m.w * 0.5, 3); x.fillRect(-m.w / 2 + 9, 4, m.w * 0.3, 3);
        x.restore();
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); removeEventListener("resize", fit); };
  }, []);
  return <canvas ref={ref} className="l-sieve" aria-hidden="true" />;
}
