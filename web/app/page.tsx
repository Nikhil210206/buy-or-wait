import Planner from "@/components/Planner";
import { Footer, Masthead } from "@/components/Sections";
import { loadPresets } from "@/lib/data";

export default function Home() {
  const presets = loadPresets();

  return (
    <>
      <div className="marble-bg" aria-hidden />
      <Masthead active="planner" />
      <main className="shell">
        <header className="intro">
          <h1 className="intro-title">
            Buy <em>or</em> <span className="intro-wait">Wait?</span>
          </h1>
          <p className="intro-lede">
            Enter what you have, what comes in, what goes out, and what you want to pay for. Your cash is projected
            ninety days ahead and the verdict updates as you type:{" "}
            <em>pay now, on a plan, later, or not at all.</em>
          </p>
        </header>
        <Planner presets={presets} />
      </main>
      <Footer />
    </>
  );
}
