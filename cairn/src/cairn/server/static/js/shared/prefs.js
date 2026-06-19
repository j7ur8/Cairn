export function readPref(key, fallback, options = {}) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed = options.parse ? options.parse(raw) : raw;
    if (options.validate && !options.validate(parsed)) return fallback;
    return parsed;
  } catch (error) {
    console.error(error);
    return fallback;
  }
}

export function writePref(key, value, options = {}) {
  try {
    const serialized = options.serialize ? options.serialize(value) : String(value);
    localStorage.setItem(key, serialized);
    return true;
  } catch (error) {
    console.error(error);
    return false;
  }
}

export function parseJsonPref(raw) {
  return JSON.parse(raw);
}

export function parseNumberPref(raw) {
  return Number(raw);
}

export function parseBooleanPref(raw) {
  return raw === 'true';
}

export function parseFlagPref(raw) {
  return raw === '1';
}

export function serializeJsonPref(value) {
  return JSON.stringify(value);
}

export function serializeBooleanPref(value) {
  return value ? 'true' : 'false';
}

export function serializeFlagPref(value) {
  return value ? '1' : '0';
}

export function isFiniteNumber(value) {
  return Number.isFinite(value);
}
