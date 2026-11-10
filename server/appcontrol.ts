import type Anthropic from "@anthropic-ai/sdk";
import { config } from "./config.js";
import { memory } from "./memory.js";
import { mac, type ControlMode } from "./mac.js";
import { approvals, type UserTurn } from "./approvals.js";

/**
 * Lets Claude operate Cipher itself by voice: camera, mute, ending or restarting
 * the conversation, opening panels, and changing settings. Most commands are carried
 * out by the page; memory and computer control are server settings.
 */

const SETTINGS: Record<string, string[]> = {
  vision_model: ["fast", "accurate"],
  camera_stills: ["on", "off"],
  captions: ["on", "off"],
  floating_words: ["on", "off"],
  visual_effects: ["full", "lite"],
  interrupt_sensitivity: ["low", "normal", "high"],
  memory: ["on", "off"],
  computer_control: ["off", "ask", "full"],
};

const ACTIONS = [
  "camera_on",
  "camera_off",
  "mute_microphone",
  "end_conversation",
  "new_conversation",
  "show_transcript",
  "hide_transcript",
  "open_settings",
  "close_panels",
  "change_setting",
] as const;
type Action = (typeof ACTIONS)[number];

export const APP_TOOL: Anthropic.Tool = {
  name: "app_control",
  description: [
    "Operate this Cipher app itself when the user asks: turn the camera on or off, mute the microphone, end the conversation,",
    "start a new conversation (forgets this chat; long-term memory stays), show or hide the transcript, open Settings, close panels,",
    "or change a setting. Settings and values: " + Object.entries(SETTINGS).map(([k, v]) => `${k} (${v.join("/")})`).join(", ") + ".",
    "Mute, end and new conversation happen after you finish speaking, so say a short goodbye or confirmation first.",
  ].join(" "),
  input_schema: {
    type: "object",
    properties: {
      action: { type: "string", enum: [...ACTIONS] },
      setting: { type: "string", enum: Object.keys(SETTINGS), description: "For change_setting." },
      value: { type: "string", description: "For change_setting, e.g. \"accurate\", \"off\"." },
    },
    required: ["action"],
  },
};

export interface AppCommandResult {
  ok: boolean;
  message?: string;
}

export function describeAppControl(): string {
  const lines = [
    "You can operate this app with the app_control tool when the user asks (\"turn on the camera\", \"mute yourself\", \"end the call\", \"switch to the accurate vision model\", \"turn off captions\", \"start a new conversation\").",
    "- Muting: once muted you can't hear them, so tell them they can unmute with the mic button or the M key.",
  ];
  if (config.hosted) lines.push("- computer_control can't be changed here: this version runs in the cloud.");
  return lines.join("\n");
}

export async function runAppControl(
  call: Anthropic.ToolUseBlock,
  user: UserTurn,
  toPage: (command: Record<string, string>) => Promise<AppCommandResult>,
  report: (e: { id: string; kind: string; purpose: string; command: string; status: string; detail?: string }) => void,
): Promise<Anthropic.ToolResultBlockParam> {
  const input = (call.input ?? {}) as { action?: string; setting?: string; value?: string };
  const action = String(input.action ?? "") as Action;
  const setting = String(input.setting ?? "");
  const value = String(input.value ?? "").toLowerCase().trim();
  const result = (text: string, isError = false): Anthropic.ToolResultBlockParam => ({
    type: "tool_result",
    tool_use_id: call.id,
    content: text,
    is_error: isError || undefined,
  });
  const label = action === "change_setting" ? `set ${setting.replace(/_/g, " ")} to ${value}` : action.replace(/_/g, " ");
  const event = { id: call.id.slice(-8), kind: "app_control", purpose: label, command: `Cipher: ${label}`, status: "done" };

  if (!ACTIONS.includes(action)) return result(`Unknown action "${action}".`, true);

  if (action === "change_setting") {
    const allowed = SETTINGS[setting];
    if (!allowed) return result(`Unknown setting "${setting}". Settings: ${Object.keys(SETTINGS).join(", ")}.`, true);
    if (!allowed.includes(value)) return result(`"${value}" isn't a value for ${setting}. Use one of: ${allowed.join(", ")}.`, true);

    if (setting === "memory") {
      memory.setEnabled(value === "on");
      report(event);
      return result(`Memory is now ${value}.`);
    }
    if (setting === "computer_control") {
      if (config.hosted) return result("Computer control isn't available in the cloud version.", true);
      // Loosening safety by voice needs a clear yes, in a later turn, so a misheard word can't do it.
      if (value === "full" && mac.mode !== "full" && !approvals.approved(`app_control\ncomputer_control=full`, user)) {
        report({ ...event, status: "needs_approval", detail: "it lets Claude act on your Mac and in Chrome without asking first" });
        return result(
          "Not changed yet: switching computer control to full needs the user's OK. Ask them in one short sentence whether Claude should act on their Mac and Chrome without asking first (it will still ask before sending, buying, deleting or shutting down), then wait.",
        );
      }
      mac.setMode(value as ControlMode);
      report(event);
      return result(`Computer control is now "${value}".`);
    }
  }

  const command: Record<string, string> = { action };
  if (action === "change_setting") Object.assign(command, { setting, value });
  const r = await toPage(command);
  report({ ...event, status: r.ok ? "done" : "failed", detail: r.message });
  return result(r.ok ? `Done${r.message ? `: ${r.message}` : "."}` : `Couldn't do it: ${r.message ?? "the app didn't respond"}`, !r.ok);
}
