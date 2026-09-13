import type { Metadata } from "next";
import { Footer, Guard, Masthead, Method, Record } from "@/components/Sections";
import { loadMeta } from "@/lib/data";

export const metadata: Metadata = {
  title: "How it works — Buy or Wait?",
  description: "The forecast, the solver, and the guard that keeps messages from steering the decision.",
};

export default function About() {
  const meta = loadMeta();
  return (
    <>
      <div className="marble-bg" aria-hidden />
      <Masthead active="about" />
      <main>
        <header className="intro shell">
          <h1 className="intro-title">
            How it <em>works</em>
          </h1>
          <p className="intro-lede">
            A deterministic cash-flow engine does the arithmetic. A language model is used only to read messages and
            receipts, and everything it says is checked before it can touch your forecast.
          </p>
        </header>
        <Method />
        <Guard meta={meta} />
        <Record meta={meta} />
      </main>
      <Footer />
    </>
  );
}
