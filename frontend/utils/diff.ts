/**
 * Word-level diff (LCS) for clause comparison. Clauses are short (tens to a
 * few hundred words), so the O(n·m) table is cheap and exact.
 */
export type DiffSegment = { text: string; kind: "same" | "add" | "del" };

const tokenize = (s: string) => s.split(/(\s+)/).filter(Boolean);

export function wordDiff(before: string, after: string): { left: DiffSegment[]; right: DiffSegment[] } {
  const a = tokenize(before);
  const b = tokenize(after);
  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i]![j] = a[i] === b[j] ? dp[i + 1]![j + 1]! + 1 : Math.max(dp[i + 1]![j]!, dp[i]![j + 1]!);
    }
  }
  const left: DiffSegment[] = [];
  const right: DiffSegment[] = [];
  const push = (list: DiffSegment[], text: string, kind: DiffSegment["kind"]) => {
    const last = list.at(-1);
    if (last && last.kind === kind) last.text += text;
    else list.push({ text, kind });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push(left, a[i]!, "same");
      push(right, b[j]!, "same");
      i++;
      j++;
    } else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) {
      push(left, a[i++]!, "del");
    } else {
      push(right, b[j++]!, "add");
    }
  }
  while (i < a.length) push(left, a[i++]!, "del");
  while (j < b.length) push(right, b[j++]!, "add");
  return { left, right };
}
