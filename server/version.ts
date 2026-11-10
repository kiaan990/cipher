import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { ROOT_DIR } from "./config.js";

/**
 * A fingerprint of the browser files. Open pages compare it on every (re)connect and
 * reload themselves when the app was updated, so they never keep running old code.
 */
function fingerprint(dir: string): string {
  const hash = createHash("sha1");
  const walk = (d: string) => {
    for (const name of fs.readdirSync(d).sort()) {
      const p = path.join(d, name);
      const st = fs.statSync(p);
      if (st.isDirectory()) walk(p);
      else hash.update(`${path.relative(dir, p)}:${st.size}:${st.mtimeMs}\n`);
    }
  };
  walk(dir);
  return hash.digest("hex").slice(0, 12);
}

export const APP_VERSION = fingerprint(path.join(ROOT_DIR, "public"));
