This is a CTF project.

Currently, it is the bootstrap stage. The tasks of the bootstrap stage are:
1. Determine the type of the target question: web, pwn, reverse, crypto, forensics, misc. The question may combine multiple types, so do not assume it belongs to only one category.
2. Analyze the services and information of the question.

For web challenges, value evidence from public routes, page source, linked JavaScript/CSS/assets, API clients, parameters, authentication boundaries, source maps, frontend configuration, leaked information, and observable browser behavior.

For pwn, reverse, crypto, forensics, or misc challenges, value evidence that identifies binaries, protocols, artifacts, encodings, algorithms, file formats, runtime assumptions, and challenge-specific evidence paths.

If a flag or proof is directly exposed in accessible content, record it as a confirmed fact. Later phases handle final Goal judgment.

Do not perform actual vulnerability exploitation during bootstrap.
