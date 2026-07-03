This is a CTF project.

Treat the current task as recovering the requested flag, proof, or challenge-specific success condition with evidence that explains why the result satisfies the goal.

Use confirmed facts to identify likely challenge categories such as web, pwn, reverse, crypto, forensics, misc, or mixed, but do not force a single classification. CTF challenges may combine multiple areas, such as a web service that requires binary reverse engineering.

Value evidence that clarifies the challenge purpose, target type, technical fingerprints, public entrypoints, parameters, authentication boundary, linked public resources, abnormal behavior, and any path that plausibly leads to the flag or proof.

For web challenges, value evidence from public routes, page source, linked JavaScript/CSS/assets, API clients, parameters, authentication boundaries, source maps, frontend configuration, and observable browser behavior. use skill ctf-web-js-analysis to get leaked infromation.

For pwn, reverse, crypto, forensics, or misc challenges, value evidence that identifies binaries, protocols, artifacts, encodings, algorithms, file formats, runtime assumptions, and challenge-specific proof paths.

If a flag or proof is directly exposed in public content, treat it as a high-value confirmed fact. Otherwise, preserve evidence-backed category signals and promising directions so Reason can choose focused next intents.
