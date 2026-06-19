export const LLM_EVENT_KIND_FILTERS = Object.freeze([
  { id: 'all', label: 'All' },
  { id: 'tools', label: 'Tools' },
  { id: 'commands', label: 'Cmds' },
  { id: 'output', label: 'Output' },
  { id: 'errors', label: 'Errors' },
]);

export const LLM_EVENT_KIND_OPTIONS = Object.freeze([
  'prompt',
  'stdout',
  'stderr',
  'model_response',
  'parse_error',
  'timeout',
  'cancelled',
  'process_end',
  'result',
  'error',
  'agent_message',
  'thinking',
  'tool_call',
  'tool_result',
  'command_start',
  'command_end',
  'usage',
  'session_init',
  'api_retry',
  'system_event',
  'capability_manifest',
  'trace_parse_error',
]);

export const GRAPH_STYLES = Object.freeze([
  { selector: 'node[nodeType="origin"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#14b8a6',label:'data(label)',color:'#fff','font-size':'11px','font-weight':'bold','text-wrap':'wrap','text-max-width':'92px','text-overflow-wrap':'anywhere',width:'data(width)',height:'data(height)','border-width':0 }},
  { selector: 'node[nodeType="goal"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#f43f5e',label:'data(label)',color:'#fff','font-size':'11px','font-weight':'bold','text-wrap':'wrap','text-max-width':'92px','text-overflow-wrap':'anywhere',width:'data(width)',height:'data(height)','border-width':0 }},
  { selector: 'node[nodeType="fact"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#6366f1',label:'data(label)',color:'#fff','font-size':'10px','font-weight':'bold','text-wrap':'wrap','text-max-width':'116px','text-overflow-wrap':'anywhere',width:'data(width)',height:'data(height)','border-width':0 }},
  { selector: 'node[nodeType="in_progress"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#f59e0b','background-opacity':0.8,label:'data(label)',color:'#fff','font-size':'11px','font-weight':'bold',width:'data(width)',height:'data(height)','border-width':2,'border-color':'#d97706' }},
  { selector: 'node[nodeType="unclaimed"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#cbd5e1','background-opacity':0.5,label:'data(label)',color:'#94a3b8','font-size':'11px','font-weight':'bold',width:'data(width)',height:'data(height)','border-width':1.5,'border-color':'#94a3b8','border-style':'dashed' }},
  { selector: 'node[nodeType="bootstrap_pending"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#fff7ed','background-opacity':0.96,label:'data(label)',color:'#c2410c','font-size':'10px','font-weight':'bold',width:'data(width)',height:'data(height)','border-width':1.5,'border-color':'#fdba74','border-style':'dashed','text-wrap':'wrap','text-max-width':'70px' }},
  { selector: 'node[nodeType="bootstrap_running"]', style: { 'text-valign':'center','text-halign':'center','font-family':'-apple-system,BlinkMacSystemFont,Inter,sans-serif', shape:'round-rectangle','background-color':'#fb923c','background-opacity':0.96,label:'data(label)',color:'#fff7ed','font-size':'10px','font-weight':'bold',width:'data(width)',height:'data(height)','border-width':2,'border-color':'#ea580c','text-wrap':'wrap','text-max-width':'70px' }},
  { selector: 'edge[status="concluded"]', style: { width:2,'line-color':'#6ee7b7','target-arrow-color':'#6ee7b7','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(label)','font-size':'7px',color:'#94a3b8','text-rotation':'autorotate','text-margin-y':-9,'text-max-width':'80px','text-wrap':'ellipsis','text-background-color':'#f8fafc','text-background-opacity':0.85,'text-background-padding':'2px','text-events':'yes','arrow-scale':0.9 }},
  { selector: 'edge[status="in_progress"]', style: { width:2,'line-color':'#fbbf24','line-style':'dashed','line-dash-pattern':[8,4],'line-dash-offset':0,'target-arrow-color':'#fbbf24','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(label)','font-size':'7px',color:'#b45309','text-rotation':'autorotate','text-margin-y':-9,'text-max-width':'80px','text-wrap':'ellipsis','text-background-color':'#fffbeb','text-background-opacity':0.85,'text-background-padding':'2px','text-events':'yes','arrow-scale':0.9 }},
  { selector: 'edge[status="unclaimed"]', style: { width:1.5,'line-color':'#cbd5e1','line-style':'dashed','line-dash-pattern':[5,5],'target-arrow-color':'#cbd5e1','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(label)','font-size':'7px',color:'#94a3b8','text-rotation':'autorotate','text-margin-y':-9,'text-max-width':'80px','text-wrap':'ellipsis','text-background-color':'#f8fafc','text-background-opacity':0.85,'text-background-padding':'2px','text-events':'yes','arrow-scale':0.7 }},
  { selector: 'edge[status="bootstrap_pending"]', style: { width:2,'line-color':'#fdba74','line-style':'dashed','line-dash-pattern':[8,4],'line-dash-offset':0,'target-arrow-color':'#fdba74','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(label)','font-size':'7px',color:'#c2410c','text-rotation':'autorotate','text-margin-y':-9,'text-max-width':'88px','text-wrap':'ellipsis','text-background-color':'#fff7ed','text-background-opacity':0.92,'text-background-padding':'2px','text-events':'yes','arrow-scale':0.85 }},
  { selector: 'edge[status="bootstrap_running"]', style: { width:2.5,'line-color':'#fb923c','line-style':'dashed','line-dash-pattern':[10,4],'line-dash-offset':0,'target-arrow-color':'#fb923c','target-arrow-shape':'triangle','curve-style':'bezier',label:'data(label)','font-size':'7px',color:'#c2410c','text-rotation':'autorotate','text-margin-y':-9,'text-max-width':'88px','text-wrap':'ellipsis','text-background-color':'#fff7ed','text-background-opacity':0.92,'text-background-padding':'2px','text-events':'yes','arrow-scale':0.95 }},
  { selector: 'edge[edgeType="bootstrap_scope"]', style: { label:'',width:1.8,'curve-style':'bezier','line-style':'dotted','line-dash-pattern':[2,5],'target-arrow-shape':'triangle-backcurve','arrow-scale':0.75,'target-distance-from-node':2 }},
  { selector: '.highlight', style: { 'z-index':999 }},
  { selector: 'edge.highlight', style: { 'z-index':999 }},
  { selector: 'node.focus', style: { 'border-width':3,'border-color':'#312e81','border-opacity':0.95,'z-index':1000 }},
  { selector: 'edge.focus', style: { 'z-index':1000,'overlay-color':'#93c5fd','overlay-opacity':0.22,'overlay-padding':5 }},
  { selector: 'node.selected-fact', style: { 'border-width':0,'underlay-color':'#93c5fd','underlay-padding':8,'underlay-opacity':0.28,'z-index':1001 }},
  { selector: '.faded', style: { opacity:0.5 }},
]);

export const LAYOUT_ENGINE_SCRIPTS = Object.freeze({
  klay: ['/static/vendor/klay.js', '/static/vendor/cytoscape-klay.js'],
  elk: ['/static/vendor/elk.bundled.js', '/static/vendor/cytoscape-elk.js'],
});

export const ALL_LLM_EXECUTIONS_VALUE = '__all__';

export const SETTINGS_UI_CLASSES = Object.freeze({
  primaryButton: 'h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg bg-brand-500 text-white font-medium hover:bg-brand-600 transition disabled:opacity-40 disabled:cursor-not-allowed',
  secondaryButton: 'h-7 inline-flex items-center justify-center px-3 text-xs rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 transition disabled:opacity-40 disabled:cursor-not-allowed',
  panel: 'rounded-xl border border-slate-200 bg-slate-50/60 p-3',
  card: 'rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-sm',
  compactCard: 'rounded-xl border border-slate-200 bg-white px-3 py-2',
  fieldInput: 'px-3 py-1.5 border border-slate-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-brand-100 focus:border-brand-400 transition placeholder:text-slate-300',
});
