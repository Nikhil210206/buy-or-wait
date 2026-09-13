export type { Status } from "./engine";
import type { Scenario } from "./scenario";

export interface Preset {
  id: string;
  title: string;
  question: string;
  scenario: Scenario;
}

export interface Meta {
  counts: { requests: number; events: number; messages: number; images: number };
  status: Record<string, number>;
  score: { n: number; stats: Record<string, number> };
  usage: { calls: number; inTokens: number; outTokens: number };
  untrusted: { id: string; sentAt: string; source: string; text: string }[];
  rejectedDirectives: number;
}
