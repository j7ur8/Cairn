export function normalizeStringList(value) {
  if (Array.isArray(value)) {
    return value.map(item => String(item || '').trim()).filter(Boolean);
  }
  if (typeof value === 'string') {
    return value.split(/[,\n]+/).map(item => item.trim()).filter(Boolean);
  }
  return [];
}

export function keyValueObjectToText(value) {
  if (!value || typeof value !== 'object') return '';
  return Object.entries(value).map(([key, item]) => `${key}=${item}`).join('\n');
}

export function textToKeyValueObject(text) {
  const out = {};
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const index = line.indexOf('=');
    if (index <= 0) throw new Error(`Invalid key=value line: ${line}`);
    const key = line.slice(0, index).trim();
    const value = line.slice(index + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

export function jsonObjectToText(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '{}';
  return JSON.stringify(value, null, 2);
}

export function textToJsonObject(text) {
  const value = JSON.parse(text || '{}');
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Probe config must be a JSON object');
  }
  return value;
}
