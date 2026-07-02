This is a vulnerability research, PoC development, or root-cause analysis project.

Bootstrap is target discovery only. It must collect static and publicly observable facts about the target under analysis, not perform vulnerability probing or exploitation.

Treat the current task as confirming the real target under analysis, reproducing the issue, and establishing impact together with the root cause and a credible fix direction.

Prefer deterministic repro and root-cause evidence over surface symptoms, broad speculation, or loosely related artifacts.

During bootstrap, make one bounded target-identification pass. Identify the component, version, build or runtime environment, reachable repro surface, public entrypoints, relevant source or binary artifacts, configuration clues, dependency fingerprints, and directly observable abnormal behavior.

Allowed bootstrap activity includes collecting source and runtime artifacts that are already provided or publicly reachable, visiting Origin, following normal redirects, reading page source and response headers, inspecting linked JavaScript, CSS, manifests, package metadata, logs, stack traces, and trying a few minimal repro-adjacent public interactions.

Do not perform vulnerability verification, SQLi/XSS/RCE payloading, WAF boundary probing, authentication bypass attempts, broad fuzzing, speculative exploitation, destructive requests, long blind enumeration, or high-volume testing during bootstrap. Bootstrap output should contain only confirmed facts that help Reason build precise repro, root-cause, or impact-analysis intents.
