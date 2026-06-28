// Map each sub-dim tag to the raw cell in the Start Universe sheet that holds
// its value. The 4 composite factors (TVA, Inflation, Competitive Dynamics,
// TAM) are spreadsheet formulas — they auto-recompute when the sub-dim cells
// are updated, so this route does NOT touch them.
//
// Verified against the live sheet on 2026-05-26 (start_universe tab, row 2 header):
//   I=Alignment  J=COGS  K=Distribution  L=Blockworks Transparency Penalty
//   M=TVA (formula = I*50% + J*25% + K*25% + L)
//   N=Liquidity  (raw — python-computed each universe_update run, but allow manual override)
//   O=Liquidity Flag  P=Inflation Expectations (VLOOKUP formula)
//   Q=Market Leadership  R=Moat  S=Competitive Dynamics (formula = Q*0.5 + R*0.5)
//   T=TAM pure  U=Catalyst  V=TAM (formula = T*0.5 + U*0.5)
//   W=Leadership
//
// Token row lookup: column D (Coingecko-id), data starts at row 3.

import type { SubDim } from "./types";

export interface SubDimMapping {
  column: string;       // single letter A-Z
  label: string;        // human-readable label, matches row 2 header
}

const MAP: Record<SubDim, SubDimMapping> = {
  alignment:                { column: "I", label: "Alignment" },
  cogs:                     { column: "J", label: "COGS" },
  distribution:             { column: "K", label: "Distribution" },
  blockworks_transparency:  { column: "L", label: "Blockworks Transparency Penalty" },
  liquidity:                { column: "N", label: "Liquidity" },
  market_leadership:        { column: "Q", label: "Market Leadership" },
  moat:                     { column: "R", label: "Moat" },
  tam_pure:                 { column: "T", label: "TAM pure" },
  catalyst:                 { column: "U", label: "Catalyst" },
  leadership:               { column: "W", label: "Leadership" },
};

export const TOKEN_LOOKUP_COLUMN = "D";  // Coingecko-id
export const DATA_FIRST_ROW = 3;         // row 1 = weight hints, row 2 = header, row 3+ = tokens

export function mappingFor(subDim: SubDim): SubDimMapping {
  const m = MAP[subDim];
  if (!m) throw new Error(`unknown sub_dim: ${subDim}`);
  return m;
}

export function colLetterToIndex(col: string): number {
  return col.charCodeAt(0) - "A".charCodeAt(0);
}
