This is a CTF project.

Currently, it is the bootstrap stage. The tasks of the bootstrap stage are:
1. Determine the type of the target question: web, pwn, reverse, crypto, forensics, misc. Note that the question may also be a combination of multiple types. Therefore, it should not be assumed that the question is solely of a single type. During the problem-solving process, multiple types of issues such as reverse engineering may be encountered.
2. Analyze the services and information of the question.

For web challenges, value evidence from public routes, page source, linked JavaScript/CSS/assets, API clients, parameters, authentication boundaries, source maps, frontend configuration, leaked information, and observable browser behavior.

For pwn, reverse, crypto, forensics, or misc challenges, value evidence that identifies binaries, protocols, artifacts, encodings, algorithms, file formats, runtime assumptions, and challenge-specific proof paths.

If a flag or proof is directly exposed in public content, treat it as a high-value confirmed fact. Otherwise, preserve evidence-backed category signals and promising directions so Reason can choose focused next intents.
