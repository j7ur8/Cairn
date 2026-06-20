from __future__ import annotations

import json

from cairn.dispatcher.workers.base import DriverResult, SeedSessionDriver, WorkerExecutionContext
from cairn.shared.config import WorkerConfig, resolve_mock_behavior

_SCRIPT = """
import json,random,sys,time

try:
    cfg=json.loads(sys.argv[1])
    prompt=json.loads(sys.argv[2])
    phase=prompt["phase"]
    phase_cfg=cfg[phase]
except Exception as exc:
    print(f"mock setup failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
delay=phase_cfg["delay"]
time.sleep(random.uniform(delay["min"],delay["max"]))

weights=dict(phase_cfg["outcomes"])
if phase=="reason":
    if not prompt.get("open_intents"):
        weights.pop("noop",None)
    if not prompt.get("fact_ids"):
        weights.pop("complete",None)
        weights.pop("intent",None)
choices=[(name,weight) for name,weight in weights.items() if weight>0]
if not choices:
    print(f"mock {phase} has no legal outcomes for prompt context", file=sys.stderr)
    raise SystemExit(2)

def _rule_matches(rule, prompt):
    fact_ids = prompt.get("fact_ids") or []
    open_intents = prompt.get("open_intents") or []
    if "fact_ids_gte" in rule and len(fact_ids) < rule["fact_ids_gte"]:
        return False
    if "fact_ids_lte" in rule and len(fact_ids) > rule["fact_ids_lte"]:
        return False
    if "open_intents_empty" in rule and (len(open_intents) == 0) != rule["open_intents_empty"]:
        return False
    return True

rules = phase_cfg.get("rules") or []
forced = None
for rule in rules:
    if _rule_matches(rule, prompt):
        forced = rule["force"]
        break

if forced is not None:
    outcome = forced
else:
    pick=random.uniform(0,sum(weight for _,weight in choices))
    total=0
    outcome=choices[-1][0]
    for name,weight in choices:
        total+=weight
        if pick<=total:
            outcome=name
            break

if phase=="healthcheck":
    raise SystemExit(0 if outcome=="ok" else 1)
if outcome=="command_fail":
    print(f"mock {phase} command failed", file=sys.stderr)
    raise SystemExit(1)
if outcome=="invalid_json":
    print("{invalid json")
    raise SystemExit(0)
if phase=="reason":
    fact_ids=prompt.get("fact_ids") or []
    max_i=prompt.get("max_intents",3)
    from_ids=[random.choice(fact_ids)] if fact_ids else []
    if outcome=="complete":
        payload=json.dumps({"accepted":True,"data":{"complete":{"from":from_ids,"description":f"mock complete from {from_ids[0]}"}}}, ensure_ascii=False)
        print(f"32173462130721312360912{payload}32173462130721312360912")
    elif outcome=="intent":
        count=random.randint(1,max(1,max_i))
        intents=[]
        for idx in range(count):
            fi=[random.choice(fact_ids)] if fact_ids else []
            intents.append({"from":fi,"description":f"mock intent {idx+1} from {fi[0] if fi else 'none'}"})
        payload=json.dumps({"accepted":True,"data":{"intents":intents}}, ensure_ascii=False)
        print(f"84913462130721312360912{payload}84913462130721312360912")
    elif outcome=="noop":
        payload=json.dumps({"accepted":True,"data":{}}, ensure_ascii=False)
        print(f"00003462130721312360912{payload}00003462130721312360912")
    elif outcome=="rejected":
        print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
    else:
        print(json.dumps({"accepted":True,"data":{"complete":{"description":"mock invalid payload"}}}, ensure_ascii=False))
    raise SystemExit(0)

if phase=="bootstrap":
    if outcome=="fact":
        print("32173462130721312360912mock fact for bootstrap32173462130721312360912")
    elif outcome=="rejected":
        print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
    else:
        print("mock invalid payload")
    raise SystemExit(0)

if phase=="bootstrap_conclude":
    if outcome=="fact":
        print("32173462130721312360912mock fact for bootstrap_conclude32173462130721312360912")
    elif outcome=="rejected":
        print("mock_rejected")
    else:
        print("mock invalid payload")
    raise SystemExit(0)

if outcome=="fact":
    label = prompt.get("intent_id") or phase
    if phase in ("explore_execute","explore_conclude"):
        print(f"32173462130721312360912mock fact for {label}32173462130721312360912")
    else:
        print(json.dumps({"accepted":True,"data":{"description":f"mock fact for {label}"}} , ensure_ascii=False))
elif outcome=="rejected":
    print(json.dumps({"accepted":False,"reason":"mock_rejected"}, ensure_ascii=False))
else:
    print(json.dumps({"accepted":True,"data":{}}, ensure_ascii=False))
""".strip()


def _compile_script() -> str:
    """Validate the embedded mock script at import time.

    The mock worker body runs in a child ``python3 -c`` process, so a syntax
    error would otherwise only surface when a mock task executes. Compiling it
    here turns that into an import-time failure with a clear message.
    """
    try:
        compile(_SCRIPT, "<mock-worker-script>", "exec")
    except SyntaxError as exc:  # pragma: no cover - guards against future edits
        raise RuntimeError(f"mock worker script has a syntax error: {exc}") from exc
    return _SCRIPT


_SCRIPT = _compile_script()


class MockDriver(SeedSessionDriver):
    type_name = "mock"

    @staticmethod
    def _argv(worker: WorkerConfig, prompt: str) -> list[str]:
        behavior = resolve_mock_behavior(worker.name, worker.env)
        return ["python3", "-c", _SCRIPT, json.dumps(behavior, ensure_ascii=False), prompt]

    def build_healthcheck(self, worker: WorkerConfig) -> list[str]:
        return self._argv(worker, '{"phase":"healthcheck"}')

    def build_execute(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str | None,
        context: WorkerExecutionContext | None = None,
    ) -> DriverResult:
        return DriverResult(argv=self._argv(worker, prompt), session=session)

    def build_conclude(
        self,
        worker: WorkerConfig,
        prompt: str,
        session: str,
        context: WorkerExecutionContext | None = None,
    ) -> list[str]:
        return self._argv(worker, prompt)
