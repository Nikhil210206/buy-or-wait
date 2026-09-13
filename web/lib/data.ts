import fs from "node:fs";
import path from "node:path";
import type { Meta, Preset } from "./types";

const read = <T,>(name: string): T =>
  JSON.parse(fs.readFileSync(path.join(process.cwd(), "public", "data", name), "utf8"));

export const loadPresets = () => read<Preset[]>("presets.json");
export const loadMeta = () => read<Meta>("meta.json");
