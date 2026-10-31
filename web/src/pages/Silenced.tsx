import { useNavigate } from "react-router-dom";
import { get, post, type Mail, type Page, type Rule } from "../api";
import { Top } from "../App";
import { Banner, MailRow, Pager, Tag, errorText, toast, useLoad, usePages } from "../components";
import { BulkBar, SelectBox, rowKey, runMany, useSelection } from "../bulk";

/** Audit of everything a rule or a taught template kept quiet. */
export function Silenced() {
  const navigate = useNavigate();
  const mail = usePages((before) => get<Page<Mail>>("/messages", { view: "silenced", limit: 30, before }), [], ["mail", "new_mail", "folders"]);
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
  const items = mail.data?.items ?? [];
  const sel = useSelection(`${mail.page}`);
  const ordered = items.map(rowKey);
  async function notLikeThese(ids: string[]) {
    const ok = await runMany(ids, (id) => post(`/messages/${id}/unsilence`));
    toast(ok === ids.length ? `${ok} back in your feed. Mail like ${ok === 1 ? "it" : "them"} won't be silenced again.` : `${ok} of ${ids.length} back in your feed; try the rest again.`);
    sel.clear();
    mail.reload();
  }
  return (
    <>
      <Top title="Silenced mail" refresh />
      <section className="page">
        <p className="lede">Everything a rule or a silenced template kept quiet: stored and searchable, never notified. Check here when a rule seems too greedy.</p>
        {mail.error && <Banner tone="err">{mail.error}</Banner>}
        {mail.data && <Pager page={mail.page} pages={mail.pages} total={mail.total} onPrev={mail.onPrev} onNext={mail.onNext} />}
        <BulkBar sel={sel} items={items} total={mail.total} match={{ view: "silenced" }} place={{ kind: "silenced" }}
          extra={(ids) => ids.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => notLikeThese(ids)} data-tip="Bring them back to the feed and stop silencing mail like them">Not like this</button>} />
        <div className={`list ${sel.size || sel.all ? "selecting" : ""}`}>
          {mail.data?.items.length === 0 && <div className="empty">Nothing silenced yet.</div>}
          {mail.data?.items.map((m, n) => (
            <MailRow key={m.id} m={m} n={n + 1} onOpen={() => navigate(`/mail/${m.id}`)}
              lead={<SelectBox sel={sel} k={rowKey(m)} ordered={ordered} label={`Select mail from ${m.sender_name || m.sender}`} />} extra={<>
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
