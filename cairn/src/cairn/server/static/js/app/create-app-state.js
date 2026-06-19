export function createAppState(...parts) {
  const seen = new Set();
  for (const part of parts) {
    for (const key of Object.keys(part)) {
      if (seen.has(key)) {
        console.error('[createAppState] duplicate app state key overwritten:', key);
      }
      seen.add(key);
    }
  }
  return Object.assign({}, ...parts);
}
