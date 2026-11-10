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
  /** The one question currently waiting for an answer. A newer question replaces it. */
  private asked: { key: string; at: number; userTurn: number } | null = null;

  /**
   * True only if `key` is the question asked most recently, it was asked in the user's
   * previous turn, and their very next words say yes. So a "yeah" can only ever answer
   * the one thing Cipher just asked, never something older. Otherwise records the question.
   */
  approved(key: string, user: UserTurn): boolean {
    const a = this.asked;
    if (a && a.key === key && Date.now() - a.at <= TTL_MS && user.turn === a.userTurn + 1 && YES.test(user.text) && !NO.test(user.text)) {
      this.asked = null;
      return true;
    }
    // Asking again in the same turn (a retry) keeps the original question's turn.
    if (!(a && a.key === key && a.userTurn === user.turn)) this.asked = { key, at: Date.now(), userTurn: user.turn };
    return false;
  }

  clear(): void {
    this.asked = null;
  }
}

export const approvals = new Approvals();
