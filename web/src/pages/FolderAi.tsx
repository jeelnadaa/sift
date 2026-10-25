/** "AI for this folder": file new mail here by what the AI understood, sort into subfolders,
 * and ask the AI to work over the mail already here (timelines, to-dos, sorting). */
import { useEffect, useState } from "react";
import { get, patch, post, type AiStatus, type AiTask, type Folder } from "../api";
import { Toggle, TextField, errorText, toast, useLoad } from "../components";
import { fullTime } from "../util";

export const CATEGORY_LABELS: Record<string, string> = {
  placement_announcement: "Placement drive", registration: "Registration", assessment_link: "Online test", interview: "Interview",
  result: "Result", recruiter: "Recruiter", action_needed: "Needs action", fyi: "FYI",
};
const SORTS: [string, string, string][] = [
  ["off", "Off", "Mail stays in this folder"],
  ["company", "By company", "One subfolder per company (from the timeline). No extra AI cost"],
  ["sender", "By sender", "One subfolder per sender. No AI needed"],
  ["ai", "By your instruction", "The AI picks or makes a subfolder for each mail (a small AI call per mail)"],
];
const KINDS: [AiTask["kind"], string, string][] = [
  ["timelines", "Build company timelines", "Put every mail here on its company's timeline (Deals). Mail the AI never read is read once"],
  ["todos", "Make to-dos", "A to-do (with deadline reminders) for every mail here that needs action"],
  ["sort", "Sort into subfolders", "Move the mail here into subfolders, made as needed"],
];
export const TASK_DONE: Record<AiTask["kind"], string> = { timelines: "joined timelines", todos: "to-dos made", sort: "moved", fill: "filed" };

export function FolderAi({ f, onChanged }: { f: Folder; onChanged: () => void }) {
  const ai = useLoad(() => get<AiStatus>("/ai"), []);
  const tasks = useLoad(() => get<{ tasks: AiTask[] }>("/ai-tasks"), [f.id]);
  const [instruction, setInstruction] = useState<string | null>(null);
  const [taskInstruction, setTaskInstruction] = useState("");
  const [withSub, setWithSub] = useState(true);
  const mine = (tasks.data?.tasks ?? []).filter((t) => t.folder_id === f.id).slice(0, 5);
  const running = mine.some((t) => t.status === "queued" || t.status === "running");
  const aiOn = !!ai.data?.ai_enabled;
  const rule = f.ai_rule ?? { categories: [], timeline: false };
  const [query, setQuery] = useState<string | null>(null);
  const [describe, setDescribe] = useState<string | null>(null);
  const q = query ?? rule.query ?? "", d = describe ?? rule.describe ?? "";
  const dirty = q.trim() !== (rule.query ?? "") || d.trim() !== (rule.describe ?? "");
  async function saveCriteria() {
    await save({ ai_rule: { categories: rule.categories, timeline: rule.timeline, query: q.trim() || null, describe: d.trim() || null } });
    setQuery(null); setDescribe(null);
  }
  async function fill() {
    try {
      const r = await post<{ status: string; changed?: number }>(`/folders/${f.id}/ai-tasks`, { kind: "fill" });
      toast(r.status === "done" ? `Filed ${r.changed} mail already here` : "The AI is filing matching mail. You'll get a notification");
      tasks.reload();
    } catch (e) { toast(errorText(e)); }
  }

  useEffect(() => {  // follow a running task's progress
    if (!running) return;
    const t = window.setInterval(() => tasks.reload(), 2000);
    return () => window.clearInterval(t);
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(changes: object) {
    try { await patch(`/folders/${f.id}`, changes); onChanged(); } catch (e) { toast(errorText(e)); }
  }
  function toggleCategory(c: string) {
    const cats = rule.categories.includes(c) ? rule.categories.filter((x) => x !== c) : [...rule.categories, c];
    save({ ai_rule: { ...rule, categories: cats } });
  }
  async function start(kind: AiTask["kind"]) {
    try {
      await post(`/folders/${f.id}/ai-tasks`, { kind, include_subfolders: withSub, instruction: kind === "sort" && taskInstruction.trim() ? taskInstruction.trim() : undefined });
      toast("Started. You'll get a notification when it's done");
      tasks.reload();
    } catch (e) { toast(errorText(e)); }
  }

  if (f.smart) return null;
  return (
    <details className="card folder-ai" open={!!(f.ai_rule || f.auto_sort)}>
      <summary><b>✦ AI for this folder</b>
        <span className="dim">{[f.ai_rule && "files new mail here", f.auto_sort && `sorts ${f.auto_sort === "ai" ? "by your instruction" : `by ${f.auto_sort}`}`].filter(Boolean).join(" · ") || "Off"}</span>
      </summary>
      {!aiOn && <p style={{ color: "var(--warn)", fontSize: 13 }}>Add an API key to enable AI filing, sorting by instruction and AI tasks (Settings → AI provider). Sorting by sender works without one.</p>}

      <div className="fa-sec">
        <div className="fa-h">File new mail here when the AI reads it as</div>
        <div className="inline">
          {Object.entries(CATEGORY_LABELS).map(([c, label]) => (
            <button key={c} className={`chip ${rule.categories.includes(c) ? "on" : ""}`} disabled={!aiOn} onClick={() => toggleCategory(c)}>{label}</button>
          ))}
          <span className="inline dim" style={{ fontSize: 13 }}><Toggle on={rule.timeline} disabled={!aiOn} label="Mail on a company timeline"
            onChange={(v) => save({ ai_rule: { ...rule, timeline: v } })} /> or mail that joins a company timeline</span>
        </div>
      </div>

      <div className="fa-sec">
        <div className="fa-h">Also file new mail here when it</div>
        <div className="stack" style={{ gap: 8, maxWidth: 680 }}>
          <TextField value={q} onChange={setQuery} maxLength={500} code ariaLabel="Search for this folder"
            placeholder="matches a search (free): from:nvidia.com  or  subject:internship" />
          <TextField value={d} onChange={(v) => { if (aiOn || !v) setDescribe(v); }} maxLength={200} ariaLabel="Description for this folder"
            placeholder={aiOn ? "and/or is described as (the AI checks while reading it): e.g. course announcements" : "Add an AI key to describe mail in words"} />
          <div className="inline">
            <button className="btn btn-primary btn-sm" disabled={!dirty} onClick={saveCriteria}>Save</button>
            {(rule.query || rule.describe) && !dirty && <button className="btn btn-ghost btn-sm" disabled={running} onClick={fill}
              data-tip={rule.describe ? "The AI checks the last 30 days, 25 mails per small call" : "Free: files every stored mail matching the search"}>File matching mail already here</button>}
            <span className="dim" style={{ fontSize: 12.5 }}>A mail can be in several folders and groups at once, and on its timeline.</span>
          </div>
        </div>
      </div>

      <div className="fa-sec">
        <div className="fa-h">Sort mail filed here into subfolders</div>
        <div className="inline">
          {SORTS.map(([mode, label, tip]) => (
            <button key={mode} className={`chip ${(f.auto_sort ?? "off") === mode ? "on" : ""}`} data-tip={tip}
              disabled={mode === "ai" && !aiOn}
              onClick={() => mode === "ai" && !f.auto_sort_instruction ? setInstruction("") : save({ auto_sort: mode })}>{label}</button>
          ))}
        </div>
        {(f.auto_sort === "ai" || instruction !== null) && (
          <div className="inline" style={{ marginTop: 8, alignItems: "flex-start" }}>
            <div style={{ flex: 1 }}><TextField value={instruction ?? f.auto_sort_instruction ?? ""} onChange={setInstruction} maxLength={500}
              placeholder="How to group, e.g. one folder per course code" ariaLabel="Sorting instruction" /></div>
            <button className="btn btn-primary btn-sm" style={{ height: 42 }} disabled={!(instruction ?? f.auto_sort_instruction ?? "").trim()}
              onClick={() => { save({ auto_sort: "ai", auto_sort_instruction: (instruction ?? f.auto_sort_instruction ?? "").trim() }); setInstruction(null); }}>Save</button>
          </div>
        )}
      </div>

      <div className="fa-sec">
        <div className="fa-h">Ask the AI to work on the mail already here</div>
        <div className="inline">
          {KINDS.map(([kind, label, tip]) => (
            <button key={kind} className="btn btn-ghost btn-sm" data-tip={tip} disabled={running || (!aiOn && !(kind === "sort" && f.auto_sort === "sender" && !taskInstruction))}
              onClick={() => start(kind)}>{label}</button>
          ))}
          <span className="inline dim" style={{ fontSize: 13 }}><Toggle on={withSub} onChange={setWithSub} label="Include subfolders" /> Include subfolders</span>
        </div>
        <div style={{ marginTop: 8, maxWidth: 560 }}>
          <TextField value={taskInstruction} onChange={setTaskInstruction} maxLength={500} ariaLabel="Sorting instruction for this run"
            placeholder="Optional, for sorting: how to group this time (else the folder's own sorting, or by company)" />
        </div>
        {mine.length > 0 && (
          <div className="fa-tasks">
            {mine.map((t) => (
              <div key={t.id} className="inline" style={{ justifyContent: "space-between" }}>
                <span>{t.kind === "fill" ? "File matching mail" : KINDS.find(([k]) => k === t.kind)?.[1]} <span className="dim">· {fullTime(t.created_at)}</span></span>
                <span className="dim" data-tip={t.note ?? undefined}>
                  {t.status === "queued" ? "Waiting…" : t.status === "running" ? `${t.done} of ${t.total}…` : `${t.changed} ${TASK_DONE[t.kind]} of ${t.done}`}
                  {" · "}{t.tokens.toLocaleString()} tokens{t.status === "stopped" ? " · stopped at the daily cap" : t.status === "failed" ? " · failed" : ""}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}
