/**
 * Lazy, shared access to RDKit.js (RDKit compiled to WebAssembly, BSD-3).
 *
 * The ~7 MB module is fetched only the first time a structure is drawn,
 * then reused. Depictions are cached by SMILES and size, so re-rendering a
 * table does not redraw every molecule.
 */
import type { MainModule as RDKitModule } from "@rdkit/rdkit";

export type { RDKitModule };

/** Pixel size of a depiction. */
export interface DepictionSize {
  width: number;
  height: number;
}

let loading: Promise<RDKitModule> | null = null;

/** Load RDKit.js once; a failed load is retried on the next call. */
export function loadRDKit(): Promise<RDKitModule> {
  if (!loading) {
    loading = (async () => {
      const [{ default: initRDKitModule }, { default: wasmUrl }] = await Promise.all([
        import("@rdkit/rdkit"),
        import("@rdkit/rdkit/RDKit_minimal.wasm?url"),
      ]);
      return initRDKitModule({ locateFile: () => wasmUrl });
    })();
    loading.catch(() => {
      loading = null;
    });
  }
  return loading;
}

const MAX_CACHED = 500;
const cache = new Map<string, string | null>();

/**
 * Draw a structure as SVG with a transparent background.
 *
 * @returns The SVG markup, or `null` if RDKit cannot parse the SMILES.
 */
export function depictSvg(rdkit: RDKitModule, smiles: string, size: DepictionSize): string | null {
  const key = `${size.width}x${size.height}:${smiles}`;
  const cached = cache.get(key);
  if (cached !== undefined) {
    return cached;
  }
  const mol = rdkit.get_mol(smiles);
  let svg: string | null = null;
  if (mol) {
    try {
      svg = mol.is_valid()
        ? mol.get_svg_with_highlights(
            JSON.stringify({ width: size.width, height: size.height, backgroundColour: [1, 1, 1, 0] }),
          )
        : null;
    } finally {
      mol.delete();
    }
  }
  if (cache.size >= MAX_CACHED) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) {
      cache.delete(oldest);
    }
  }
  cache.set(key, svg);
  return svg;
}
