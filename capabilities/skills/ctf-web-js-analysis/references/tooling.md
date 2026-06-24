# Tooling Reference

Third-party sources are vendored under `tools/vendor/`. Run `scripts/install_vendor_tools.sh` from the skill directory to install/build dependencies. Some tools require Go, Node.js, Python, or network access for package installation.

## jsluice

Purpose: JavaScript URL, secret, and API-like object extraction.

Typical use:

```bash
go run ./tools/vendor/jsluice/cmd/jsluice urls < file.js
go run ./tools/vendor/jsluice/cmd/jsluice secrets < file.js
```

Limit: static extraction only. Treat output as candidates unless cross-validated.

## LinkFinder

Purpose: endpoint extraction from JavaScript.

Typical use:

```bash
python3 tools/vendor/LinkFinder/linkfinder.py -i file.js -o cli
```

Limit: regex-heavy; can miss framework-generated routes and produce false positives.

## xnLinkFinder

Purpose: endpoint extraction with broader filtering and output options.

Typical use:

```bash
python3 tools/vendor/xnLinkFinder/xnLinkFinder.py -i file.js -o endpoints.txt
```

Limit: tune scope filters carefully in multi-domain apps.

## katana

Purpose: crawl authorized targets and collect URLs, scripts, forms, and endpoints.

Typical use:

```bash
go run ./tools/vendor/katana/cmd/katana -u https://target.example -js-crawl -silent
```

Limit: crawling must stay inside authorized CTF scope. Avoid large fuzzing or aggressive depth during bootstrap.

## gitleaks

Purpose: secret scanning in downloaded frontend artifacts.

Typical use:

```bash
go run ./tools/vendor/gitleaks detect --no-git --source artifacts/js --report-format json --report-path artifacts/gitleaks.json
```

Limit: redact full secret values in final outputs.

## trufflehog

Purpose: verified and pattern-based secret scanning.

Typical use:

```bash
go run ./tools/vendor/trufflehog filesystem artifacts/js --json > artifacts/trufflehog.json
```

Limit: online verification may contact third-party services; disable or avoid verification unless explicitly authorized.

## retire.js

Purpose: identify vulnerable third-party JavaScript libraries.

Typical use:

```bash
node tools/vendor/retire.js/node/cli.js --path artifacts/js --outputformat json --outputpath artifacts/retire.json
```

Limit: dependency findings are not business API findings. Put them in leak/dependency findings only when useful.

## js-beautify

Purpose: format minified JavaScript for manual review.

Typical use:

```bash
node tools/vendor/js-beautify/js/bin/js-beautify.js input.min.js -o formatted/input.js
```

Limit: formatting changes line numbers. Preserve original file hashes and cite the original whenever possible.
