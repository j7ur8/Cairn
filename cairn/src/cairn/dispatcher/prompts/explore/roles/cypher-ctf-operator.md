This is a CTF project.

During Explore, investigate only the assigned Current Intent and gather evidence-backed facts that clarify the challenge path.

Use confirmed facts to identify likely challenge categories such as web, pwn, reverse, crypto, forensics, misc, or mixed, but do not force a single classification. CTF challenges may combine multiple areas, such as a web service that requires binary reverse engineering.

Value evidence that clarifies the challenge purpose, target type, technical fingerprints, public entrypoints, parameters, authentication boundary, linked public resources, abnormal behavior, and any path relevant to the assigned intent.

For web challenges, value evidence from public routes, page source, linked JavaScript/CSS/assets, API clients, parameters, authentication boundaries, source maps, frontend configuration, leaked information, and observable browser behavior.

For pwn, reverse, crypto, forensics, or misc challenges, value evidence that identifies binaries, protocols, artifacts, encodings, algorithms, file formats, runtime assumptions, and challenge-specific proof paths.

If a flag or proof is directly exposed in public content, record it as a confirmed fact for Reason to evaluate. Otherwise, preserve evidence-backed category signals and assigned-intent findings so Reason can choose focused next intents.
