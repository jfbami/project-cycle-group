export type RiskTier = 'very_high' | 'high' | 'moderate' | 'low' | 'very_low';

export const ALL_TIERS: RiskTier[] = ['very_high', 'high', 'moderate', 'low', 'very_low'];

export const TIER_META: Record<RiskTier, { label: string; color: string; range: string }> = {
  very_high: { label: 'Very High', color: '#ef4444', range: '≥ 90th pct' },
  high:      { label: 'High',      color: '#f97316', range: '70–89th'    },
  moderate:  { label: 'Moderate',  color: '#eab308', range: '40–69th'    },
  low:       { label: 'Low',       color: '#84cc16', range: '20–39th'    },
  very_low:  { label: 'Very Low',  color: '#22c55e', range: '< 20th'     },
};

/** One selected intersection — normalised from the GeoJSON feature properties. */
export interface SelectedIntersection {
  intersectionId: number;
  name: string;
  // ── Model output ─────────────────────────────────────────
  riskScore: number;        // 0–100 percentile rank
  riskTier: RiskTier;
  predictedCrashes: number; // raw NB SPF prediction
  ebPredicted: number;      // EB-shrunk prediction
  observedCrashes: number;  // actual count over window
  yearsObserved: number;
  // ── Vision Zero severity counts ───────────────────────────
  injuryTotal: number;
  ksiTotal: number;         // Killed or Seriously Injured
  fatalTotal: number;
  pedTotal: number;
  bikeTotal: number;
  // ── Infrastructure features ───────────────────────────────
  isSignalized: boolean;
  numLegs: number;
  maxSpeedLimit: number;
  bikeFacility: string;
  arterialClass: string;
  coordinates: { lat: number; lng: number };
}

export interface LayerVisibility {
  circles: boolean;
  bikeFacility: boolean;
}

export interface ScorecardStats {
  count: number;
  crashes: number;
  injuries: number;
  ksi: number;
  fatal: number;
  ped: number;
  bike: number;
}
