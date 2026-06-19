export function parseBracketMeta(metaText) {
  const tokens = [];
  const text = (metaText || '').trim();
  let current = '';
  let quote = null;
  for (const ch of text) {
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === '\'') {
      current += ch;
      quote = ch;
      continue;
    }
    if (/\s/.test(ch)) {
      if (current) {
        tokens.push(current);
        current = '';
      }
      continue;
    }
    current += ch;
  }
  if (current) tokens.push(current);

  const result = {};
  for (const token of tokens) {
    const idx = token.indexOf('=');
    if (idx <= 0) continue;
    const key = token.slice(0, idx);
    let value = token.slice(idx + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith('\'') && value.endsWith('\''))) {
      value = value.slice(1, -1);
    }
    result[key] = value;
  }
  return result;
}

export function parseCypherSummary(text, expectedPrefix, mode) {
  const trimmed = (text || '').trim();
  if (!trimmed.startsWith(expectedPrefix)) return null;
  const closing = trimmed.indexOf(']');
  if (closing < 0) return null;
  const header = trimmed.slice(expectedPrefix.length, closing).trim();
  const rest = trimmed.slice(closing + 1).trim();
  return {
    mode,
    headline: rest.split(/\n+/)[0]?.trim() || '',
    body: rest,
    meta: parseBracketMeta(header),
    raw: trimmed,
  };
}

export function createSummaryHelpers() {
  return {
    parseBracketMeta,
    parseCypherSummary,

    summaryView(text, kind = 'plain') {
      const trimmed = (text || '').trim();
      if (!trimmed) return { mode: 'plain', headline: '', body: '', meta: {}, raw: '' };
      if (kind === 'fact') {
        const finding = parseCypherSummary(trimmed, '[cypher:finding', 'cypher_finding');
        if (finding) return finding;
      }
      if (kind === 'intent' || kind === 'reason') {
        const intent = parseCypherSummary(trimmed, '[cypher:intent', 'cypher_intent');
        if (intent) return intent;
      }
      const replay = typeof this.parseReplaySummary === 'function' ? this.parseReplaySummary(trimmed) : null;
      if (replay) return replay;
      return {
        mode: 'plain',
        headline: trimmed.split(/\n+/)[0]?.trim() || '',
        body: trimmed,
        meta: {},
        raw: trimmed,
      };
    },

    summaryHeadline(view) {
      return view?.headline || '';
    },

    summaryBody(view) {
      if (!view) return '';
      if (view.mode === 'plain') return view.body || '';
      const headline = view.headline || '';
      const body = view.body || '';
      if (!body) return '';
      return body === headline ? '' : body;
    },

    summaryMetaItems(view) {
      if (!view?.meta) return [];
      const entries = Object.entries(view.meta).filter(([, value]) => value !== null && value !== undefined && String(value).trim() !== '');
      const preferredOrder = ['type', 'confidence', 'severity', 'lane', 'priority', 'expected', 'cost', 'destructiveness', 'triggers', 'tags', 'artifacts', 'cleanup', 'expected_source_fact'];
      entries.sort((a, b) => {
        const aIdx = preferredOrder.indexOf(a[0]);
        const bIdx = preferredOrder.indexOf(b[0]);
        if (aIdx === -1 && bIdx === -1) return a[0].localeCompare(b[0]);
        if (aIdx === -1) return 1;
        if (bIdx === -1) return -1;
        return aIdx - bIdx;
      });
      return entries.map(([key, value]) => ({ key: key.replaceAll('_', ' '), value: String(value) }));
    },

    summaryHasMeta(view) {
      return this.summaryMetaItems(view).length > 0;
    },

    summaryCardViewModel(text, kind = 'plain') {
      const raw = String(text || '');
      const cacheKey = `${kind}:${raw}`;
      const cached = this._summaryCardCache.get(cacheKey);
      if (cached) return cached;
      const view = this.summaryView(raw, kind);
      const metaItems = this.summaryMetaItems(view);
      const model = {
        view,
        headline: this.summaryHeadline(view),
        body: this.summaryBody(view),
        metaItems,
        hasMeta: metaItems.length > 0,
      };
      this._summaryCardCache.set(cacheKey, model);
      this._summaryCardCacheOrder.push(cacheKey);
      while (this._summaryCardCacheOrder.length > 300) {
        const staleKey = this._summaryCardCacheOrder.shift();
        this._summaryCardCache.delete(staleKey);
      }
      return model;
    },
  };
}
