/** Form model for the rule editor: flat condition rows and exception groups <-> the rule
 * engine's JSON tree (backend app/rules.py). Same shapes as the Android editor. */
import type { Cond, Leaf } from "./api";

export interface CondKind { key: string; label: string; field: string; op: string; inputLabel: string; hint: string; list: boolean }

export const KINDS: CondKind[] = [
  { key: "sender_domain", label: "Sender domain is", field: "sender_domain", op: "in", inputLabel: "Domains, comma separated", hint: "kotak.com, slice.bank.in", list: true },
  { key: "sender", label: "Sender address is", field: "sender", op: "in", inputLabel: "Addresses, comma separated", hint: "alerts@kotak.com", list: true },
  { key: "subject_any", label: "Subject contains any of", field: "subject", op: "contains_any", inputLabel: "Words or phrases, comma separated", hint: "debited, credited, UPI", list: true },
  { key: "subject_regex", label: "Subject matches (regex)", field: "subject", op: "matches", inputLabel: "Regular expression", hint: "\\b(debited|credited)\\b", list: false },
  { key: "body_any", label: "Body contains any of", field: "body", op: "contains_any", inputLabel: "Words or phrases, comma separated", hint: "fraud, blocked", list: true },
  { key: "amount_above", label: "Amount above ₹", field: "amount", op: "gt", inputLabel: "Rupees", hint: "2000", list: false },
  { key: "amount_below", label: "Amount below ₹", field: "amount", op: "lt", inputLabel: "Rupees", hint: "500", list: false },
  { key: "label", label: "Gmail label is", field: "label", op: "has", inputLabel: "Gmail label", hint: "CATEGORY_PROMOTIONS", list: false },
  { key: "header", label: "Header is present", field: "header", op: "present", inputLabel: "Header name", hint: "List-Unsubscribe", list: false },
  { key: "attachment", label: "Has an attachment", field: "has_attachment", op: "is", inputLabel: "", hint: "", list: false },
];
export const kind = (key: string) => KINDS.find((k) => k.key === key) ?? KINDS[0];

export interface Row { kind: string; text: string }

const values = (text: string) => text.split(",").map((s) => s.trim()).filter(Boolean);

export function rowToLeaf(r: Row): Leaf | null {
  const k = kind(r.kind);
  if (k.key === "attachment") return { field: k.field, op: "is", value: true };
  if (k.field === "amount") {
    const n = Number(r.text.replace(/[,₹\s]/g, ""));
    return r.text.trim() && isFinite(n) && n >= 0 ? { field: k.field, op: k.op, value: n } : null;
  }
  if (!k.list) return r.text.trim() ? { field: k.field, op: k.op, value: r.text.trim() } : null;
  const v = values(r.text);
  return v.length ? { field: k.field, op: k.op, value: v } : null;
}

export function leafToRow(o: Leaf): Row | null {
  const { field, op, value } = o;
  if (!field || !op) return null;
  const text = Array.isArray(value) ? value.join(", ") : value === undefined || value === null || typeof value === "boolean" ? "" : String(value);
  let key: string | null = null;
  if (field === "sender_domain") key = "sender_domain";
  else if (field === "sender" && (op === "is" || op === "in")) key = "sender";
  else if (field === "subject") key = op === "matches" ? "subject_regex" : "subject_any";
  else if (field === "body") key = "body_any";
  else if (field === "amount" && (op === "gt" || op === "gte")) key = "amount_above";
  else if (field === "amount" && (op === "lt" || op === "lte")) key = "amount_below";
  else if (field === "label") key = "label";
  else if (field === "header") key = "header";
  else if (field === "has_attachment" && value !== false) key = "attachment";
  return key ? { kind: key, text } : null;
}

const isLeaf = (c: unknown): c is Leaf => !!c && typeof c === "object" && "field" in (c as object);

/** {all|any: [leaves]} or one leaf -> rows; null when the shape can't be edited in the form. */
export function treeToRows(tree: Cond | null | undefined): { all: boolean; rows: Row[] } | null {
  if (!tree) return { all: true, rows: [] };
  if (isLeaf(tree)) { const r = leafToRow(tree); return r ? { all: true, rows: [r] } : null; }
  const items = "all" in tree ? tree.all : "any" in tree ? tree.any : null;
  if (!items) return null;
  const rows: Row[] = [];
  for (const it of items) { const r = isLeaf(it) ? leafToRow(it) : null; if (!r) return null; rows.push(r); }
  return { all: "all" in tree, rows };
}

/** {any: [leaf | {all: [leaves]}]} -> groups; null when not editable here. */
export function exceptionGroups(tree: Cond | null | undefined): Row[][] | null {
  if (!tree) return [];
  const items: Cond[] = "any" in tree ? tree.any : [tree];
  const out: Row[][] = [];
  for (const it of items) {
    if (isLeaf(it)) { const r = leafToRow(it); if (!r) return null; out.push([r]); continue; }
    if (!("all" in it)) return null;
    const g: Row[] = [];
    for (const l of it.all) { const r = isLeaf(l) ? leafToRow(l) : null; if (!r) return null; g.push(r); }
    out.push(g);
  }
  return out;
}

export function rowsToTree(all: boolean, rows: Row[]): Cond | null {
  const leaves = rows.map(rowToLeaf).filter((l): l is Leaf => l !== null);
  if (!leaves.length) return null;
  return all ? { all: leaves } : { any: leaves };
}

export function groupsToTree(groups: Row[][]): Cond | null {
  const items: Cond[] = [];
  for (const g of groups) {
    const leaves = g.map(rowToLeaf).filter((l): l is Leaf => l !== null);
    if (leaves.length === 1) items.push(leaves[0]);
    else if (leaves.length > 1) items.push({ all: leaves });
  }
  return items.length ? { any: items } : null;
}

/** Plain-language summary for shapes the form can't edit. */
export function describe(tree: Cond | null | undefined): string {
  if (!tree) return "";
  if ("all" in tree) return "(" + tree.all.map(describe).join(" and ") + ")";
  if ("any" in tree) return "(" + tree.any.map(describe).join(" or ") + ")";
  if ("not" in tree) return "not " + describe(tree.not);
  const r = leafToRow(tree);
  return r ? `${kind(r.kind).label.toLowerCase()} ${r.text}`.trim() : JSON.stringify(tree);
}
