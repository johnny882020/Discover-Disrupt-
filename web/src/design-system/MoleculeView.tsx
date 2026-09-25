/**
 * Renders a compound's structure.
 *
 * TODO(follow-up): this is a v1 placeholder that renders the SMILES string
 * as monospace text. The plan calls for an actual 2D structure rendering
 * via RDKit.js compiled to WASM; wiring that renderer (loading the WASM
 * module, drawing to a <canvas>/SVG, handling load failures) is a
 * documented follow-up and is deliberately out of scope for this pass.
 */
export function MoleculeView({ smiles }: { smiles: string | null }): React.JSX.Element {
  if (!smiles) {
    return <span className="text-xs text-ink/40 dark:text-paper/40">No structure</span>;
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
