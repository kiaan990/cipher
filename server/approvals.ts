/**
 * Approvals shared by Mac control and Chrome control. When an action needs the user's
 * OK, it's recorded here; it may run only if the user's own words, in a later turn,
 * say yes. Claude's claims never count.
 */

const TTL_MS = 3 * 60_000;
const YES = /\b(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|please do|confirm(ed)?|approved?|go for it|sounds good|absolutely|of course|fine|send it)\b/i;
const NO = /\b(no|nope|don'?t|do not|stop|cancel|wait|never ?mind|hold on)\b/i;

export interface UserTurn {
  /** What the user actually said most recently. */
  text: string;
  /** Which of their turns that was. */
  turn: number;
}

class Approvals {
  private readonly pending = new Map<string, { at: number; userTurn: number }>();

  /** True if `key` was asked about in an earlier turn and the user has now said yes. Otherwise records the question. */
  approved(key: string, user: UserTurn): boolean {
    for (const [k, p] of this.pending) if (Date.now() - p.at > TTL_MS) this.pending.delete(k);
    const asked = this.pending.get(key);
    if (asked && user.turn > asked.userTurn && YES.test(user.text) && !NO.test(user.text)) {
      this.pending.delete(key);
      return true;
    }
    this.pending.set(key, { at: Date.now(), userTurn: user.turn });
    return false;
  }

  clear(): void {
    this.pending.clear();
  }
}

export const approvals = new Approvals();
