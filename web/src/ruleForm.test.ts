import { describe as suite, expect, it } from "vitest";
import { describe, exceptionGroups, groupsToTree, rowsToTree, treeToRows } from "./ruleForm";
import { flatten, humanize, relativeTime, safeUrl, subtreeIds } from "./util";
import type { Folder } from "./api";

suite("rule form", () => {
  const bank = {
    all: [
      { field: "sender_domain", op: "in", value: ["kotak.com", "slice.in"] },
      { field: "subject", op: "matches", value: "\\b(debited|credited)\\b" },
    ],
  };
  const exc = { any: [{ field: "subject", op: "contains_any", value: ["fraud"] }, { all: [{ field: "amount", op: "gt", value: 2000 }, { field: "subject", op: "contains_any", value: ["debited"] }] }] };

  it("round-trips the bank rule and its exception groups", () => {
    const parsed = treeToRows(bank)!;
    expect(parsed.rows.map((r) => r.kind)).toEqual(["sender_domain", "subject_regex"]);
    expect(rowsToTree(parsed.all, parsed.rows)).toEqual(bank);
    const groups = exceptionGroups(exc)!;
    expect(groups.map((g) => g.length)).toEqual([1, 2]);
    expect(groupsToTree(groups)).toEqual(exc);
  });

  it("drops empty rows and refuses shapes it can't edit", () => {
    expect(rowsToTree(true, [{ kind: "subject_any", text: " , " }])).toBeNull();
    expect(rowsToTree(true, [{ kind: "amount_above", text: "₹2,000" }])).toEqual({ all: [{ field: "amount", op: "gt", value: 2000 }] });
    expect(treeToRows({ all: [{ not: { field: "subject", op: "contains_any", value: ["x"] } }] })).toBeNull();
    expect(describe({ not: { field: "label", op: "has", value: "SPAM" } })).toBe("not gmail label is SPAM");
  });
});

suite("util", () => {
  it("humanizes pill text", () => {
    expect(humanize("assessment_link")).toBe("Assessment link");
    expect(humanize(null)).toBe("");
  });

  it("only opens http(s) links", () => {
    expect(safeUrl("https://hirepro.in/t/8dk2")).toBe("https://hirepro.in/t/8dk2");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("not a url")).toBeNull();
  });

  it("formats relative times", () => {
    const now = new Date("2026-10-24T12:00:00Z");
    expect(relativeTime("2026-10-24T11:59:30Z", now)).toBe("now");
    expect(relativeTime("2026-10-24T11:15:00Z", now)).toBe("45m");
    expect(relativeTime("2026-10-24T07:00:00Z", now)).toBe("5h");
    expect(relativeTime("2026-10-21T12:00:00Z", now)).toBe("3d");
  });

  it("flattens the folder tree depth first and finds subtrees", () => {
    const f = (id: string, children: Folder[] = []): Folder => ({ id, parent_id: null, name: id, color: null, icon: null, position: 0, pinned: false, notify_mode: "default", smart: false, ai_rule: null, auto_sort: null, auto_sort_instruction: null, threads: 0, unread: 0, unread_total: 0, children });
    const tree = [f("a", [f("a1", [f("a1x")]), f("a2")]), f("b")];
    expect(flatten(tree).map(([x, d]) => `${x.id}:${d}`)).toEqual(["a:0", "a1:1", "a1x:2", "a2:1", "b:0"]);
    expect(flatten(tree, new Set(["a"])).map(([x]) => x.id)).toEqual(["a", "a1", "a2", "b"]);
    expect([...subtreeIds(tree[0])].sort()).toEqual(["a", "a1", "a1x", "a2"]);
  });
});
