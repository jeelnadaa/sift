import { useNavigate } from "react-router-dom";
import { get, post, type Mail, type Page, type Rule } from "../api";
import { Top } from "../App";
import { Banner, MailRow, Tag, errorText, toast, useLoad } from "../components";

/** Audit of everything a rule or a taught template kept quiet. */
export function Silenced() {
  const navigate = useNavigate();
  const mail = useLoad(() => get<Page<Mail>>("/messages", { view: "silenced", limit: 200 }));
  const rules = useLoad(() => get<Rule[]>("/rules"));
  const ruleName = (id: string | null) => (id ? rules.data?.find((r) => r.id === id)?.name ?? "A rule" : null);

  async function notLikeThis(m: Mail) {
    try {
      const r = await post<{ rule_id: string | null }>(`/messages/${m.id}/unsilence`);
      mail.reload();
      const rule = rules.data?.find((x) => x.id === r.rule_id);
      toast(rule ? `Back in your feed. "${rule.name}" silenced it: edit the rule so it doesn't happen again.` : "Back in your feed. Mail like this won't be silenced again.");
    } catch (e) { toast(errorText(e)); }
  }
  return (
    <>
      <Top title="Silenced mail" />
      <section className="page">
        <p className="lede">Everything a rule or a silenced template kept quiet: stored and searchable, never notified. Check here when a rule seems too greedy.</p>
        {mail.error && <Banner tone="err">{mail.error}</Banner>}
        <div className="list">
          {mail.data?.items.length === 0 && <div className="empty">Nothing silenced yet.</div>}
          {mail.data?.items.map((m) => (
            <MailRow key={m.id} m={m} onOpen={() => navigate(`/mail/${m.id}`)} extra={<>
              <Tag tone={m.matched_rule_id ? undefined : "digest"}>{ruleName(m.matched_rule_id) ?? "Silenced template"}</Tag>
              {m.matched_rule_id && <button className="chip" onClick={(e) => { e.stopPropagation(); navigate(`/rules/${m.matched_rule_id}`); }}>Edit rule</button>}
              <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); notLikeThis(m); }}>Not like this</button>
            </>} />
          ))}
        </div>
      </section>
    </>
  );
}
