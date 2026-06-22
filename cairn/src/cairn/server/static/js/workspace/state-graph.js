import { GRAPH_STYLES, LAYOUT_ENGINE_SCRIPTS } from '../shared/constants.js';

export function createWorkspaceGraphState() {
  return {
    cy: null,
    selectedNode: null,
    selectedFacts: [],
    layoutMode: 'dagre_tb',
    layoutLoading: false,
    _graphSignature: '',
    graphMode: 'graph',
    async ensureLayoutEngineLoaded(mode = this.layoutMode) {
      const engine = this.layoutEngine(mode);
      const scripts = LAYOUT_ENGINE_SCRIPTS[engine] || [];
      if (scripts.length === 0) return;
      await scripts.reduce((promise, src) => promise.then(() => this.loadScriptOnce(src)), Promise.resolve());
    },

    isValidLayoutMode(mode) {
      return ['dagre_tb', 'dagre_lr', 'klay_tb', 'klay_lr', 'elk_tb', 'elk_lr'].includes(mode);
    },

    layoutEngine(mode = this.layoutMode) {
      if (mode.startsWith('elk')) return 'elk';
      return mode.startsWith('klay') ? 'klay' : 'dagre';
    },

    layoutDirection(mode = this.layoutMode) {
      return mode.endsWith('_lr') ? 'LR' : 'TB';
    },

    openIntentNodeType(intent) {
      if (this.isBootstrapIntent(intent)) return intent.worker ? 'bootstrap_running' : 'bootstrap_pending';
      return intent.worker ? 'in_progress' : 'unclaimed';
    },

    openIntentNodeLabel(intent) {
      return intent.id;
    },

    openIntentNodeSize(intent) {
      return { width: 52, height: 28 };
    },

    filenameFromContentDisposition(value) {
      const header = String(value || '');
      const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
      if (utf8Match) return decodeURIComponent(utf8Match[1].replace(/"/g, ''));
      const plainMatch = header.match(/filename="?([^";]+)"?/i);
      return plainMatch ? plainMatch[1] : '';
    },

    buildElements() {
      const nodes = [];
      const edges = [];
      for (const f of this.project.facts) {
        const nodeType = f.id === 'origin' ? 'origin' : f.id === 'goal' ? 'goal' : 'fact';
        const label = this.summarizeFactLabel(f);
        const size = this.factNodeSize(label, nodeType);
        nodes.push({ data: {
          id: f.id,
          label,
          description: f.description,
          nodeType,
          width: size.width,
          height: size.height,
        }});
      }
      for (const intent of this.project.intents) {
        const lbl = intent.id;
        if (intent.to) {
          for (const src of intent.from) {
            edges.push({ data: { id: `${intent.id}_${src}`, source: src, target: intent.to, intentId: intent.id, label: lbl, status: 'concluded' }});
          }
        } else {
          const phId = `_ph_${intent.id}`;
          const nodeSize = this.openIntentNodeSize(intent);
          const nodeType = this.openIntentNodeType(intent);
          nodes.push({ data: {
            id: phId,
            label: this.openIntentNodeLabel(intent),
            description: intent.description,
            nodeType,
            intentId: intent.id,
            width: nodeSize.width,
            height: nodeSize.height,
          }});
          for (const src of intent.from) {
            edges.push({ data: { id: `${intent.id}_${src}`, source: src, target: phId, intentId: intent.id, label: lbl, status: nodeType }});
          }
          if (this.isBootstrapIntent(intent)) {
            edges.push({ data: { id: `${intent.id}_goal`, source: phId, target: 'goal', intentId: intent.id, label: '', status: nodeType, edgeType: 'bootstrap_scope' }});
          }
        }
      }
      return { nodes, edges };
    },

    graphSignatureFromElements(nodes, edges) {
      const nodeSig = nodes
        .map(node => `${node.data.id}:${node.data.label}:${node.data.width}:${node.data.height}`)
        .sort()
        .join('|');
      const edgeSig = edges
        .map(edge => `${edge.data.id}:${edge.data.source}->${edge.data.target}:${edge.data.edgeType || ''}`)
        .sort()
        .join('|');
      return `${nodeSig}::${edgeSig}`;
    },

    graphEdgeDataChanged(current, next) {
      return current.data('status') !== next.status
        || current.data('label') !== next.label
        || current.data('edgeType') !== next.edgeType
        || current.data('intentId') !== next.intentId;
    },

    async initGraph() {
      const container = document.getElementById('cy');
      if (!container) return;
      try {
        this.layoutLoading = true;
        await this.ensureLayoutEngineLoaded();
      } catch (error) {
        this.showToast(error.message, 'error');
        this.layoutMode = 'dagre_tb';
        this.localPrefs.layout_mode = 'dagre_tb';
        this.saveLocalPrefs();
      } finally {
        this.layoutLoading = false;
      }
      const { nodes, edges } = this.buildElements();
      this._graphSignature = this.graphSignatureFromElements(nodes, edges);
      const rawCy = cytoscape({
        container,
        elements: [...nodes, ...edges],
        style: this.graphStyles(),
        layout: this.layoutOpts(),
        minZoom: 0.15, maxZoom: 3.5,
      });
      this.cy = rawCy;
      const self = this;
      rawCy.on('tap', 'node', e => self.onNodeTap(e));
      rawCy.on('tap', 'edge', e => self.onEdgeTap(e));
      rawCy.on('tap', e => { if (e.target === rawCy) self.clearSelection(); });
      this.setupAutoFit();
      this.settleGraphViewport();
    },

    graphStyles() {
      return GRAPH_STYLES;
    },

    layoutOpts() {
      const direction = this.layoutDirection();
      if (this.layoutEngine() === 'elk') {
        const elkDirection = direction === 'TB' ? 'DOWN' : 'RIGHT';
        return {
          name: 'elk',
          fit: true,
          padding: 50,
          animate: false,
          elk: {
            algorithm: 'layered',
            'elk.direction': elkDirection,
            'elk.aspectRatio': '1.5',
            'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
            'elk.spacing.nodeNode': '50',
            'elk.layered.spacing.nodeNodeBetweenLayers': '80',
            'elk.spacing.edgeNode': '25',
            'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
            'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
          },
        };
      }
      if (this.layoutEngine() === 'klay') {
        const isHorizontal = direction === 'LR';
        return {
          name: 'klay',
          fit: true,
          padding: 50,
          animate: false,
          klay: {
            direction: direction === 'TB' ? 'DOWN' : 'RIGHT',
            edgeRouting: 'POLYLINE',
            crossingMinimization: 'LAYER_SWEEP',
            nodeLayering: 'NETWORK_SIMPLEX',
            nodePlacement: 'BRANDES_KOEPF',
            separateConnectedComponents: true,
            spacing: isHorizontal ? 52 : 40,
            inLayerSpacingFactor: isHorizontal ? 1.15 : 1.0,
            thoroughness: 8,
          },
        };
      }
      return {
        name: 'dagre',
        rankDir: direction,
        nodeSep: 60,
        rankSep: 80,
        padding: 50,
        fit: true,
        animate: false,
      };
    },

    snapshotNodePositions() {
      const positions = new Map();
      if (!this.cy) return positions;
      this.cy.nodes().forEach(node => {
        positions.set(node.id(), { x: node.position('x'), y: node.position('y') });
      });
      return positions;
    },

    anchorPositionFromIds(nodeIds, previousPositions, offset = 36) {
      const anchors = [];
      for (const nodeId of nodeIds) {
        const existing = this.cy?.getElementById(nodeId);
        if (existing?.length) {
          anchors.push({ x: existing.position('x'), y: existing.position('y') });
          continue;
        }
        const previous = previousPositions.get(nodeId);
        if (previous) anchors.push(previous);
      }
      if (anchors.length === 0) return null;
      const center = anchors.reduce((acc, pos) => ({ x: acc.x + pos.x, y: acc.y + pos.y }), { x: 0, y: 0 });
      const avg = { x: center.x / anchors.length, y: center.y / anchors.length };
      return this.layoutDirection() === 'TB'
        ? { x: avg.x, y: avg.y + offset }
        : { x: avg.x + offset, y: avg.y };
    },

    initialPositionForNode(nodeData, previousPositions) {
      if (!this.project) return null;
      if (nodeData.intentId) {
        const previousPlaceholder = previousPositions.get(nodeData.id);
        if (previousPlaceholder) return previousPlaceholder;
        const intent = this.project.intents.find(item => item.id === nodeData.intentId);
        return intent ? this.anchorPositionFromIds(intent.from, previousPositions, 32) : null;
      }

      const producingIntent = this.project.intents.find(item => item.to === nodeData.id);
      if (!producingIntent) return null;
      const placeholderPosition = previousPositions.get(`_ph_${producingIntent.id}`);
      if (placeholderPosition) return placeholderPosition;
      return this.anchorPositionFromIds(producingIntent.from, previousPositions, 44);
    },

    updateGraph(options = {}) {
      if (!this.cy || !this.project) return;
      const { nodes, edges } = this.buildElements();
      const nextSignature = this.graphSignatureFromElements(nodes, edges);
      const wantNodes = new Set(nodes.map(n => n.data.id));
      const wantEdges = new Set(edges.map(e => e.data.id));
      const previousPositions = this.snapshotNodePositions();
      let changed = false;
      let layoutChanged = nextSignature !== this._graphSignature;

      this.cy.nodes().forEach(n => { if (!wantNodes.has(n.id())) { n.remove(); changed = true; layoutChanged = true; } });
      this.cy.edges().forEach(e => { if (!wantEdges.has(e.id())) { e.remove(); changed = true; layoutChanged = true; } });

      for (const n of nodes) {
        const ex = this.cy.getElementById(n.data.id);
        if (ex.length === 0) {
          const initialPosition = this.initialPositionForNode(n.data, previousPositions);
          this.cy.add(initialPosition ? { ...n, position: initialPosition } : n);
          changed = true;
          layoutChanged = true;
        } else if (
          ex.data('nodeType') !== n.data.nodeType ||
          ex.data('label') !== n.data.label ||
          ex.data('description') !== n.data.description ||
          ex.data('width') !== n.data.width ||
          ex.data('height') !== n.data.height
        ) {
          ex.data(n.data); changed = true;
        }
      }
      for (const e of edges) {
        const ex = this.cy.getElementById(e.data.id);
        if (ex.length === 0) {
          this.cy.add(e);
          changed = true;
          layoutChanged = true;
        } else if (this.graphEdgeDataChanged(ex, e.data)) {
          ex.data(e.data);
        }
      }
      if (layoutChanged) {
        this._graphSignature = nextSignature;
        void this.ensureLayoutEngineLoaded()
          .then(() => this.cy?.layout(this.layoutOpts()).run())
          .catch((error) => this.showToast(error.message, 'error'));
      }
      this.refreshGraphDecorations();
    },

    fitGraph() { if (this.cy) this.cy.fit(undefined, 50); },

    settleGraphViewport() {
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const container = document.getElementById('cy');
            if (!this.cy || !container || this.view !== 'graph' || this.graphMode !== 'graph') return;
            const rect = container.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) return;
            this.cy.resize();
            this.cy.fit(undefined, 50);
          });
        });
      });
    },

    centerGraphOnElements(eles) {
      if (!this.cy || !eles || eles.length === 0) return;
      this.cy.center(eles);
    },

    centerGraphOnFact(factId) {
      if (!this.cy || !factId) return;
      const node = this.cy.getElementById(factId);
      if (node.length > 0) this.centerGraphOnElements(node);
    },

    centerGraphOnIntent(intentId) {
      if (!this.cy || !intentId) return;
      const edges = this.cy.edges(`[intentId="${intentId}"]`);
      if (edges.length === 0) return;
      this.centerGraphOnElements(edges.add(edges.sources()).add(edges.targets()));
    },

    summarizeFactLabel(fact) {
      return fact.id;
    },

    factNodeSize(label, nodeType) {
      const preset = nodeType === 'fact'
        ? { fontSize: 10, maxTextWidth: 116, minWidth: 52, minHeight: 34, paddingX: 10, paddingY: 10 }
        : { fontSize: 11, maxTextWidth: 92, minWidth: 58, minHeight: 38, paddingX: 10, paddingY: 10 };

      const measured = this.measureWrappedText(label, preset.maxTextWidth, preset.fontSize);
      return {
        width: Math.max(preset.minWidth, Math.ceil(measured.width + preset.paddingX * 2)),
        height: Math.max(preset.minHeight, Math.ceil(measured.height + preset.paddingY * 2)),
      };
    },

    measureWrappedText(text, maxWidth, fontSize) {
      const content = (text || '').trim() || ' ';
      const lines = [];
      let currentWidth = 0;
      let currentChars = 0;
      let maxLineWidth = 0;

      const pushLine = () => {
        if (currentChars === 0 && lines.length > 0) lines.push(0);
        else if (currentChars > 0) lines.push(currentWidth);
        maxLineWidth = Math.max(maxLineWidth, currentWidth);
        currentWidth = 0;
        currentChars = 0;
      };

      for (const char of Array.from(content)) {
        if (char === '\n') {
          pushLine();
          continue;
        }
        const charWidth = this.estimateLabelCharWidth(char, fontSize);
        if (currentChars > 0 && currentWidth + charWidth > maxWidth) pushLine();
        currentWidth += charWidth;
        currentChars += 1;
      }

      pushLine();

      const lineCount = Math.max(1, lines.length);
      const lineHeight = fontSize * 1.35;
      return {
        width: Math.min(maxWidth, Math.max(fontSize * 1.6, maxLineWidth)),
        height: lineCount * lineHeight,
      };
    },

    estimateLabelCharWidth(char, fontSize) {
      if (/\s/.test(char)) return fontSize * 0.35;
      if (/[\u1100-\u115F\u2E80-\uA4CF\uAC00-\uD7A3\uF900-\uFAFF\uFE10-\uFE6F\uFF00-\uFF60\uFFE0-\uFFE6]/.test(char)) {
        return fontSize * 1.0;
      }
      return fontSize * 0.58;
    },

    setupAutoFit() {
      this.teardownAutoFit();
      const container = document.getElementById('cy');
      if (!container || !this.cy) return;
      let fitTimer = null;
      this._resizeObserver = new ResizeObserver(() => {
        clearTimeout(fitTimer);
        fitTimer = setTimeout(() => {
          if (this.cy) {
            const clampedWidth = this.clampPanelWidth(this.sidePanelWidth);
            if (clampedWidth !== this.sidePanelWidth) {
              this.sidePanelWidth = clampedWidth;
              this.saveSidePanelWidth();
            }
            const clampedLlmWidth = this.clampLlmPanelWidth(this.llmPanelWidth);
            if (clampedLlmWidth !== this.llmPanelWidth) {
              this.llmPanelWidth = clampedLlmWidth;
              this.saveLlmPanelPrefs();
            }
            this.settleGraphViewport();
          }
        }, 200);
      });
      this._resizeObserver.observe(container);
    },

    teardownAutoFit() {
      if (this._resizeObserver) {
        this._resizeObserver.disconnect();
        this._resizeObserver = null;
      }
    },
    async applySelectedLayout() {
      this.layoutMode = this.isValidLayoutMode(this.layoutMode) ? this.layoutMode : 'dagre_tb';
      this.localPrefs.layout_mode = this.layoutMode;
      this.saveLocalPrefs();
      if (!this.cy) return;
      try {
        this.layoutLoading = true;
        await this.ensureLayoutEngineLoaded();
        this.cy.layout(this.layoutOpts()).run();
      } catch (error) {
        this.showToast(error.message, 'error');
        this.layoutMode = 'dagre_tb';
        this.localPrefs.layout_mode = 'dagre_tb';
        this.saveLocalPrefs();
        this.cy.layout(this.layoutOpts()).run();
      } finally {
        this.layoutLoading = false;
      }
    },

    clearGraphSelection(preserveTimeline = false) {
      this.selectedNode = null;
      this.selectedFacts = [];
      if (!preserveTimeline) this.selectedTimelineEntryId = null;
      if (this.cy) this.cy.elements().removeClass('highlight focus faded selected-fact');
    },

    clearSelection() {
      this.clearGraphSelection(false);
    },

    toggleFactSelection(fid) {
      this.selectedTimelineEntryId = null;
      const idx = this.selectedFacts.indexOf(fid);
      if (idx >= 0) {
        this.selectedFacts.splice(idx, 1);
        if (this.selectedFacts.length === 0) {
          this.clearSelection();
          return;
        }
        if (this.selectedNode?.type === 'fact' && this.selectedNode.id === fid) {
          this.selectedNode = { type:'fact', id: this.selectedFacts[this.selectedFacts.length - 1] };
        }
      } else {
        this.selectedFacts.push(fid);
        this.selectedNode = { type:'fact', id: fid };
      }
      this.refreshGraphDecorations();
    },

    removeFactSelection(fid) {
      this.selectedTimelineEntryId = null;
      const idx = this.selectedFacts.indexOf(fid);
      if (idx < 0) return;
      this.selectedFacts.splice(idx, 1);
      if (this.selectedFacts.length === 0) {
        this.clearSelection();
        return;
      }
      if (this.selectedNode?.type === 'fact' && this.selectedNode.id === fid) {
        this.selectedNode = { type:'fact', id: this.selectedFacts[this.selectedFacts.length - 1] };
      }
      this.refreshGraphDecorations();
    },

    onNodeTap(e) {
      const node = e.target;
      const id = node.data('id');
      const nt = node.data('nodeType');
      const keepLogFocus = this.sideTab === 'log';

      if (['in_progress', 'unclaimed', 'bootstrap_pending', 'bootstrap_running'].includes(nt)) {
        this.selectIntent(node.data('intentId'));
        if (keepLogFocus) this.scrollTimelineToSelection();
        else this.sideTab = 'detail';
        return;
      }
      if (e.originalEvent.shiftKey) {
        this.toggleFactSelection(id);
        if (keepLogFocus) this.scrollTimelineToSelection();
        else this.sideTab = 'detail';
        return;
      } else {
        this.selectedFacts = [id];
        this.selectFact(id);
      }
      if (keepLogFocus) this.scrollTimelineToSelection();
      else this.sideTab = 'detail';
    },

    onEdgeTap(e) {
      this.selectIntent(e.target.data('intentId'));
      if (this.sideTab === 'log') this.scrollTimelineToSelection();
      else this.sideTab = 'detail';
    },

    selectIntent(intent) {
      const intentId = typeof intent === 'string' ? intent : intent?.id;
      if (!intentId) return;
      this.selectedFacts = [];
      this.selectedTimelineEntryId = null;
      this.selectedNode = { type:'intent', id: intentId };
      this.applyLineageHighlightForIntent(intentId);
      this.syncLlmExecutionSelectionForIntent?.(intentId);
    },

    selectFact(fact) {
      const factId = typeof fact === 'string' ? fact : fact?.id;
      if (!factId) return;
      if (!this.selectedFacts.includes(factId)) this.selectedFacts = [factId];
      this.selectedTimelineEntryId = null;
      this.selectedNode = { type:'fact', id: factId };
      if (this.selectedFacts.length > 1) {
        this.applyMultiFactSelectionHighlight();
        return;
      }
      this.applyLineageHighlightForFact(factId);
    },

    refreshGraphDecorations() {
      if (!this.selectedNode) {
        this.syncFactSelections();
        return;
      }
      if (this.selectedNode.type === 'intent') this.applyLineageHighlightForIntent(this.selectedNode.id);
      if (this.selectedNode.type === 'fact') {
        if (this.selectedFacts.length > 1 && this.selectedFacts.includes(this.selectedNode.id)) {
          this.applyMultiFactSelectionHighlight();
          return;
        }
        this.applyLineageHighlightForFact(this.selectedNode.id);
      }
    },

    syncFactSelections() {
      if (!this.cy) return;
      this.cy.nodes().removeClass('selected-fact');
      for (const fid of this.selectedFacts) {
        const node = this.cy.getElementById(fid);
        if (node.length > 0) node.addClass('selected-fact');
      }
    },

    collectFactLineage(fid) {
      const upstreamFacts = new Set();
      const upstreamIntents = new Set();

      const walkFactUpstream = (factId) => {
        if (upstreamFacts.has(factId) || !this.project) return;
        upstreamFacts.add(factId);
        for (const intent of this.project.intents) {
          if (intent.to === factId) walkIntentUpstream(intent.id);
        }
      };

      const walkIntentUpstream = (iid) => {
        if (upstreamIntents.has(iid) || !this.project) return;
        upstreamIntents.add(iid);
        const intent = this.project.intents.find(i => i.id === iid);
        if (!intent) return;
        for (const sourceId of intent.from) walkFactUpstream(sourceId);
      };

      walkFactUpstream(fid);
      return { upstreamFacts, upstreamIntents };
    },

    collectIntentElements(intent, nodeIds, edgeIds) {
      if (intent.to) nodeIds.add(intent.to);
      else nodeIds.add(`_ph_${intent.id}`);
      for (const sourceId of intent.from) {
        nodeIds.add(sourceId);
        edgeIds.add(`${intent.id}_${sourceId}`);
      }
      if (this.isBootstrapIntent(intent)) {
        nodeIds.add('goal');
        edgeIds.add(`${intent.id}_goal`);
      }
    },

    applyLineageHighlightForIntent(intentId) {
      if (!this.cy || !this.project) return;
      const intent = this.project.intents.find(i => i.id === intentId);
      if (!intent) return;
      this.cy.elements().removeClass('highlight focus faded');

      const nodeIds = new Set();
      const edgeIds = new Set();
      this.collectIntentElements(intent, nodeIds, edgeIds);
      const highlightNodes = this.cy.nodes().filter(n => nodeIds.has(n.id()));
      const focusEdges = this.cy.edges().filter(e => edgeIds.has(e.id()));

      highlightNodes.addClass('highlight');
      focusEdges.addClass('focus');

      const visible = highlightNodes.add(focusEdges);
      this.cy.elements().not(visible).addClass('faded');
      this.syncFactSelections();
    },

    applyLineageHighlightForFact(factId) {
      if (!this.cy || !this.project) return;
      const { upstreamFacts, upstreamIntents } = this.collectFactLineage(factId);
      const nodeIds = new Set(upstreamFacts);
      const edgeIds = new Set();

      for (const iid of upstreamIntents) {
        const intent = this.project.intents.find(i => i.id === iid);
        if (intent) this.collectIntentElements(intent, nodeIds, edgeIds);
      }

      this.cy.elements().removeClass('highlight focus faded');
      const highlightNodes = this.cy.nodes().filter(n => nodeIds.has(n.id()));
      const highlightEdges = this.cy.edges().filter(e => edgeIds.has(e.id()));
      const focusNode = this.cy.getElementById(factId);

      highlightNodes.addClass('highlight');
      highlightEdges.addClass('highlight');
      focusNode.addClass('focus');

      const visible = highlightNodes.add(highlightEdges).add(focusNode);
      this.cy.elements().not(visible).addClass('faded');
      this.syncFactSelections();
    },

    applyMultiFactSelectionHighlight() {
      if (!this.cy) return;
      this.cy.elements().removeClass('highlight focus faded selected-fact');
      this.syncFactSelections();
    },

    getProducingIntent(fid) {
      return this.project ? this.project.intents.find(i => i.to === fid) || null : null;
    },

    selectedFactId() {
      return this.selectedNode?.type === 'fact' ? this.selectedNode.id : null;
    },

    selectedFactRecord() {
      const factId = this.selectedFactId();
      if (!this.project || !factId) return null;
      return this.project.facts.find(f => f.id === factId) || null;
    },

    selectedFactProducingIntent() {
      const factId = this.selectedFactId();
      return factId ? this.getProducingIntent(factId) : null;
    },

    selectedFactRecords() {
      if (!this.project || this.selectedFacts.length === 0) return [];
      const factsById = new Map(this.project.facts.map(f => [f.id, f]));
      return this.selectedFacts.map(fid => factsById.get(fid)).filter(Boolean);
    },

    selectedIntentId() {
      return this.selectedNode?.type === 'intent' ? this.selectedNode.id : null;
    },

    selectedIntentRecord() {
      const intentId = this.selectedIntentId();
      if (!this.project || !intentId) return null;
      return this.project.intents.find(i => i.id === intentId) || null;
    },

    factDisplayTitle(fact) {
      return fact?.id || '';
    },

    factDisplaySubtitle(fact) {
      if (!fact) return '';
      if (fact.id === 'origin') return 'Project starting point';
      if (fact.id === 'goal') return 'Project target fact';
      const producingIntent = this.getProducingIntent(fact.id);
      return producingIntent ? `From: ${producingIntent.id}` : 'From: —';
    },

    factRelationSummary(fact) {
      if (!fact) return '';
      if (fact.id === 'origin') return '';
      if (fact.id === 'goal') return 'Project target fact';
      const producingIntent = this.getProducingIntent(fact.id);
      return producingIntent ? `Produced by ${producingIntent.id}` : '';
    },

    selectedOpenIntentRecord() {
      const intent = this.selectedIntentRecord();
      if (!intent || intent.to || !this.projectIsActive()) return null;
      return intent;
    },

    selectedActionableOpenIntentRecord() {
      const intent = this.selectedOpenIntentRecord();
      if (!intent) return null;
      const actor = this.actorName();
      return !intent.worker || intent.worker === actor ? intent : null;
    },

    selectedIntentPrimaryActionLabel() {
      const intent = this.selectedOpenIntentRecord();
      if (!intent) return 'Claim';
      if (!intent.worker) return 'Claim';
      return intent.worker === this.actorName() ? 'Heartbeat' : 'Claimed';
    },

    getFactRecord(fid) {
      return this.project ? this.project.facts.find(f => f.id === fid) || null : null;
    },

  };
}
