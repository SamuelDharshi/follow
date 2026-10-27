import Halftone from "@/components/Halftone";
import { Reveal } from "@/components/motion";

export default function PageHero({ title, sub, seed }: { title: string; sub: string; seed: number }) {
  return (
    <div className="row page-hero">
      <div className="c">
        <p className="sub fu">{sub}</p>
        <h1><Reveal text={title} /></h1>
      </div>
      <div className="c"><Halftone seed={seed} /></div>
    </div>
  );
}
