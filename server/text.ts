/** Strip formatting so the TTS voice never reads out markdown symbols. */
export function cleanForSpeech(input: string): string {
  return input
    .replace(/\[\s*mood\s*:[^\]]*\]/gi, " ") // stray mood tags
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1") // [text](url) -> text
    .replace(/^\s{0,3}#{1,6}\s+/gm, "") // headings
    .replace(/^\s*([-*•]|\d+[.)])\s+/gm, "") // list bullets
    .replace(/^\s*>\s?/gm, "") // block quotes
    .replace(/[*_`~#|<>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Buffers streamed tokens and cuts them into speakable pieces at sentence
 * boundaries, so each piece can go to TTS as soon as it is complete.
 */
export class SentenceChunker {
  private buf = "";
  private emitted = 0;

  push(delta: string): string[] {
    this.buf += delta;
    const out: string[] = [];
    for (;;) {
      const cut = this.findCut();
      if (cut < 0) break;
      const piece = cleanForSpeech(this.buf.slice(0, cut));
      this.buf = this.buf.slice(cut);
      if (piece) {
        out.push(piece);
        this.emitted++;
      }
    }
    return out;
  }

  flush(): string[] {
    const piece = cleanForSpeech(this.buf);
    this.buf = "";
    return piece ? [piece] : [];
  }

  private findCut(): number {
    // The first piece may be very short ("Sure."), which gets audio going sooner.
    const minLen = this.emitted === 0 ? 2 : 12;
    const re = /([.!?…]+["'”’)\]]*)(\s+)|\n+/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(this.buf))) {
      const before = this.buf.slice(0, m.index + (m[1]?.length ?? 0)).trim();
      if (before.length >= minLen) return m.index + m[0].length;
    }
    // A short spoken opener ("Oh, …", "Hmm, …", "Yeah, …"): its own piece, because its audio
    // is usually saved already and can play instantly while the rest is being voiced.
    if (this.emitted === 0) {
      const o = /^\s*(Oh|Ooh|Ah|Hmm|Hm|Yeah|Okay|So|Well|Honestly|Right|Haha|Yep|Sure|Mm),\s/.exec(this.buf);
      if (o) return o[0].length;
    }
    // Opening clause: cut at the first comma after a few words so the voice can
    // start before the whole first sentence has been written.
    if (this.emitted === 0) {
      const c = this.buf.indexOf(", ", 14);
      if (c > 0) return c + 2;
    }
    // Runaway sentence: cut at the last comma or space.
    if (this.buf.length > 240) {
      const c = this.buf.lastIndexOf(", ");
      if (c > 40) return c + 2;
      const s = this.buf.lastIndexOf(" ");
      if (s > 40) return s + 1;
    }
    return -1;
  }
}
