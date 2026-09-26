/**
 * Renders a compound's 2D structure with RDKit.js.
 *
 * The SMILES text is shown while RDKit.js loads, and permanently if it
 * cannot load or cannot parse the SMILES — the structure is never hidden.
 * The depiction is an `<img>` (an SVG data URL), so drawn content can never
 * run script; in dark mode it is inverted, with hues rotated back, so bonds
 * stay visible and heteroatom colours stay recognizable.
 */
import { useEffect, useState } from "react";
import { depictSvg, loadRDKit, type DepictionSize } from "../chem/rdkit";

const SIZES: Record<"sm" | "md" | "lg", DepictionSize> = {
  sm: { width: 160, height: 100 },
  md: { width: 260, height: 180 },
  lg: { width: 420, height: 300 },
};

interface MoleculeViewProps {
  smiles: string | null;
  size?: keyof typeof SIZES;
}

export function MoleculeView({ smiles, size = "sm" }: MoleculeViewProps): React.JSX.Element {
  const dims = SIZES[size];
  const [svg, setSvg] = useState<{ smiles: string; markup: string } | null>(null);

  useEffect(() => {
    if (!smiles) {
      return;
    }
    let cancelled = false;
    loadRDKit()
      .then((rdkit) => {
        const markup = depictSvg(rdkit, smiles, dims);
        if (!cancelled && markup) {
          setSvg({ smiles, markup });
        }
      })
      .catch(() => {
        // RDKit.js unavailable: the SMILES text fallback stays in place.
      });
    return () => {
      cancelled = true;
    };
  }, [smiles, dims]);

  if (!smiles) {
    return <span className="text-xs text-ink/40 dark:text-paper/40">No structure</span>;
  }

  if (svg?.smiles === smiles) {
    return (
      <img
        src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg.markup)}`}
        alt={smiles}
        title={smiles}
        width={dims.width}
        height={dims.height}
        className="dark:[filter:invert(1)_hue-rotate(180deg)]"
      />
    );
  }

  return (
    <span
      title={smiles}
      className="inline-block max-w-[16rem] truncate rounded-sm bg-ink/5 px-2 py-1 font-mono text-xs text-ink dark:bg-paper/10 dark:text-paper"
    >
      {smiles}
    </span>
  );
}
