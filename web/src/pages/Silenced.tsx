import { useNavigate } from "react-router-dom";
import { get, post, type Mail, type Page, type Rule } from "../api";
import { Top } from "../App";
import { Banner, MailRow, Pager, Tag, errorText, toast, useLoad, usePages } from "../components";

/** Audit of everything a rule or a taught template kept quiet. */
export function Silenced() {
  const navigate = useNavigate();
  const mail = usePages((before) => get<Page<Mail>>("/messages", { view: "silenced", limit: 30, before }), []);
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
        {mail.data && <Pager page={mail.page} pages={mail.pages} total={mail.total} onPrev={mail.onPrev} onNext={mail.onNext} />}
        <div className="list">
          {mail.data?.items.length === 0 && <div className="empty">Nothing silenced yet.</div>}
          {mail.data?.items.map((m, n) => (
            <MailRow key={m.id} m={m} n={n + 1} onOpen={() => navigate(`/mail/${m.id}`)} extra={<>
              <Tag tone={m.matched_rule_id ? undefined : "digest"} tip={m.matched_rule_id ? "The rule that silenced it" : "You silenced mail like this before"}>{ruleName(m.matched_rule_id) ?? "Silenced template"}</Tag>
              {m.matched_rule_id && <button className="chip" data-tip="Open the rule that silenced this" onClick={(e) => { e.stopPropagation(); navigate(`/rules/${m.matched_rule_id}`); }}>Edit rule</button>}
              <button className="btn btn-ghost btn-sm" data-tip="Bring it back to the feed and stop silencing mail like it" onClick={(e) => { e.stopPropagation(); notLikeThis(m); }}>Not like this</button>
            </>} />
          ))}
        </div>
        {mail.data && <Pager bottom page={mail.page} pages={mail.pages} total={mail.total} onPrev={mail.onPrev} onNext={mail.onNext} />}
      </section>
    </>
  );
}
