/** Deterministic PRNG utilities — same seed, same data, every refresh. */

export type Rng = () => number

export function mulberry32(seed: number): Rng {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Stable 32-bit hash so per-entity generators don't depend on creation order. */
export function hashString(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export function pick<T>(rng: Rng, items: readonly T[]): T {
  const item = items[Math.floor(rng() * items.length)]
  if (item === undefined) throw new Error('pick from empty array')
  return item
}

/** Pick using [item, weight] pairs. */
export function pickWeighted<T>(rng: Rng, entries: readonly (readonly [T, number])[]): T {
  const total = entries.reduce((sum, [, w]) => sum + w, 0)
  let roll = rng() * total
  for (const [item, weight] of entries) {
    roll -= weight
    if (roll <= 0) return item
  }
  return entries[entries.length - 1]![0]
}

/** Integer in [min, max] inclusive. */
export function int(rng: Rng, min: number, max: number): number {
  return min + Math.floor(rng() * (max - min + 1))
}

export function float(rng: Rng, min: number, max: number): number {
  return min + rng() * (max - min)
}

/** Approximate normal via Box-Muller. */
export function normal(rng: Rng, mean: number, sd: number): number {
  const u = Math.max(rng(), 1e-9)
  const v = rng()
  return mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

export function chance(rng: Rng, p: number): boolean {
  return rng() < p
}

export function clamp(x: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, x))
}
