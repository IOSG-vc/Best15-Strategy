import { readFileSync } from "fs";
import { join } from "path";

export interface Position {
  id: string;
  executionPrice: number;
  amount: number;
  allocation: number;
}

export interface PositionsData {
  executionDate: string;
  totalDeployed: number;
  inceptionDate: string;
  inceptionDeployed: number;
  totalFundSize?: number;
  positions: Position[];
}

export function loadPositionsData(): PositionsData | null {
  try {
    const raw = readFileSync(join(process.cwd(), "data", "private_fund_positions.json"), "utf-8");
    return JSON.parse(raw) as PositionsData;
  } catch {
    return null;
  }
}
