This is a CTF project.

During bootstrap, make one bounded initial challenge triage pass. Identify likely challenge categories such as web, pwn, reverse, crypto, forensics, misc, or mixed, but do not force a single classification. CTF challenges may combine multiple areas, such as a web service that requires binary reverse engineering. Report only confirmed facts and evidence-backed category signals.

Identify the challenge purpose, target type, technical fingerprints, public entrypoints, parameters, authentication boundary, linked public resources, and directly observable abnormal behavior.

For web or likely web targets, perform frontend static analysis and JavaScript reverse engineering on publicly reachable HTML, JavaScript, CSS, source maps, frontend routes, bundled assets, configuration constants, API clients, request signing logic, encryption logic, and other exposed frontend artifacts. The goal is to recover all confirmed system API endpoints and detailed parameters.

Write recovered API information to project-relative `information_api.json` using this JSON shape: `{"apis": [], "notes": []}`. Each API entry should include confirmed `method`, `url`, and `source`, plus available details such as `params`, `headers`, `body_schema`, `auth_required`, `description`, and `evidence`. Do not invent missing parameters.

While performing static analysis and JavaScript reverse engineering, collect exposed sensitive information such as tokens, keys, credentials, internal paths, debug hints, source maps, hidden endpoints, comments, and configuration leaks. Write these findings to project-relative `information_leak.json` using this JSON shape: `{"leaks": [], "notes": []}`. Each leak entry should include `type`, `value_or_summary`, `source`, and `evidence`.

Allowed bootstrap activity includes visiting the Origin, following normal redirects, reading page source and response headers, inspecting publicly linked JavaScript and CSS, checking a few obvious public paths, and trying basic public form behavior. Do not perform deep exploitation, brute force, password guessing, large fuzzing, long blind injection or enumeration, destructive requests, or other high-volume activity during bootstrap.

Bootstrap output should contain only confirmed facts that help Reason build the next intents, including references to `information_api.json` and `information_leak.json` when those files are produced. If a flag or proof is directly exposed in public content during this bounded pass, include it as a confirmed fact.
