export function createAppState(...parts) {
  const seen = new Set();
  const duplicates = [];
  for (const part of parts) {
    for (const key of Object.keys(part)) {
      if (seen.has(key)) {
        duplicates.push(key);
      }
      seen.add(key);
    }
  }
  if (duplicates.length > 0) {
    const message = `[createAppState] duplicate app state key overwritten: ${duplicates.join(', ')}`;
    if (globalThis.CAIRN_FRONTEND_ENV !== 'production') {
      throw new Error(message);
    }
    console.error(message);
  }
  return Object.assign({}, ...parts);
}
