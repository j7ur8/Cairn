// Assembles the Alpine root component from domain slices registered on
// window.CairnParts. Each slice is a factory returning a plain object; all
// slices merge into one object so methods still call each other via `this`.
// Order of `parts` is irrelevant at runtime (this binds at call time) but the
// collision guard below flags any key defined by two slices, which would
// otherwise be silently overwritten by Object.assign.
function cairnApp() {
  const parts = [
    CairnParts.core(),
    CairnParts.graph(),
    CairnParts.llm_log(),
    CairnParts.projects(),
    CairnParts.settings(),
    CairnParts.settings_admin(),
    CairnParts.prompts(),
    CairnParts.ai_profiles(),
    CairnParts.proxies(),
    CairnParts.capabilities(),
    CairnParts.ui(),
  ];
  const seen = new Set();
  for (const part of parts) {
    for (const key of Object.keys(part)) {
      if (seen.has(key)) {
        console.error('[cairnApp] duplicate CairnParts key overwritten:', key);
      }
      seen.add(key);
    }
  }
  return Object.assign({}, ...parts);
}
