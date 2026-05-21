import type { FeatureCollection } from 'geojson';

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

/**
 * GeoJSON FeatureCollection of Points — one per intersection.
 * Properties use snake_case to match Python pipeline output:
 *   intersection_id, risk_score, risk_tier, predicted_crashes, eb_predicted,
 *   observed_crashes, years_observed, injury_total, ksi_total, fatal_total,
 *   ped_total, bike_total, is_signalized, num_legs, max_speed_limit,
 *   bike_facility, arterial_class
 */
export const fetchIntersections = () => get<FeatureCollection>('/api/intersections');
