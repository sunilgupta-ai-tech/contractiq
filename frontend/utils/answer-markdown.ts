/**
 * The small Markdown subset the answer prompt asks for (backend prompt
 * qa-v3): "### " headings, "- " / "1. " lists, paragraphs, and **bold**
 * inline. Parsed into plain data and rendered as React elements — never as
 * HTML — because answers quote uploaded, untrusted document text.
 */

export type AnswerBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

const HEADING = /^#{1,6}\s+(.*)$/;
const BULLET = /^[-*+•]\s+(.*)$/;
const NUMBERED = /^\d{1,3}[.)]\s+(.*)$/;

export function parseAnswer(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };

  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    if (!line) {
      flushParagraph();
      continue;
    }
    const heading = line.match(HEADING);
    const bullet = line.match(BULLET);
    const numbered = line.match(NUMBERED);
    if (heading) {
      flushParagraph();
      blocks.push({ kind: "heading", text: heading[1]!.replace(/\*\*/g, "") });
    } else if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      const item = (bullet ?? numbered)![1]!;
      const last = blocks.at(-1);
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(item);
      else blocks.push({ kind: "list", ordered, items: [item] });
    } else {
      paragraph.push(line);
    }
  }
  flushParagraph();
  return blocks;
}
