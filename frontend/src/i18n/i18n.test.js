import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import fr from "./fr.json";
import { setLanguage, t } from "./index";

// Every literal text passed to t() in the code
function keysInCode() {
  const keys = new Set();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (/\.jsx?$/.test(entry.name) && !entry.name.includes(".test.")) {
        const source = fs.readFileSync(file, "utf8");
        for (const m of source.matchAll(/\bt\(("(?:[^"\\]|\\.)*")/g)) keys.add(JSON.parse(m[1]));
      }
    }
  };
  walk(path.resolve(process.cwd(), "src"));
  return keys;
}

describe("translations", () => {
  it("French covers every text in the interface", () => {
    const missing = [...keysInCode()].filter((k) => !(k in fr));
    expect(missing).toEqual([]);
  });

  it("keeps the same placeholders", () => {
    const names = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const wrong = Object.entries(fr).filter(([en, text]) => names(en).join() !== names(text).join());
    expect(wrong).toEqual([]);
  });

  it("translates and fills placeholders, falling back to English", () => {
    setLanguage("fr", { reload: false });
    expect(t("Sign in")).toBe("Se connecter");
    expect(t("{n} containers", { n: 3 })).toBe("3 conteneurs");
    expect(t("Not in the catalog")).toBe("Not in the catalog");
    expect(document.documentElement.lang).toBe("fr");
    setLanguage("en", { reload: false });
    expect(t("Sign in")).toBe("Sign in");
  });
});
