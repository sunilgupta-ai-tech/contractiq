/**
 * Table clauses arrive as markdown (the backend keeps tables as markdown so
 * rows and columns survive into prompts), and quotes are whitespace-
 * collapsed onto one line:
 *
 *   "| Milestone | Due | Fee | | --- | --- | --- | | Kick-off | Week 1 | 10,000 |"
 *
 * Returns the cells as rows (header first), or null when the text is not a
 * table, so ordinary clause text is never mangled.
 */
export function parseMarkdownTable(text: string): string[][] | null {
  const trimmed = text.trim();
  if (!trimmed.startsWith("|") || !/\|\s*-{3,}\s*\|/.test(trimmed)) return null;
  // Row boundaries: "|" + newline + "|", or (after whitespace collapsing) "| |".
  const rows = trimmed
    .split(/\|\s*\n\s*\||\|\s+\|/)
    .map((row) =>
      row
        .replace(/^\s*\|/, "")
        .replace(/\|\s*$/, "")
        .split(/(?<!\\)\|/) // unescaped pipes only: "\|" is a pipe inside a cell
        .map((cell) => cell.trim().replace(/\\\|/g, "|")),
    )
    .filter((cells) => cells.some((c) => c !== "") && !cells.every((c) => /^-{3,}$/.test(c)));
  const width = rows[0]?.length ?? 0;
  return rows.length >= 2 && width >= 2 ? rows : null;
}
