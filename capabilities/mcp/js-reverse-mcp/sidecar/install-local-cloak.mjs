import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { extract as tarExtract } from 'tar';
import {
  getArchiveName,
  getBinaryDir,
  getBinaryPath,
  getChromiumVersion,
} from './node_modules/cloakbrowser/dist/config.js';

const LOCAL_ARCHIVE_MISSING_EXIT_CODE = 42;
const downloadRoot = '/opt/cairn-cloak/.cloak-downloads';

function parseChecksums(text) {
  const result = new Map();
  for (const line of text.trim().split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const match = trimmed.match(/^([a-f0-9]{64})\s+\*?(.+)$/i);
    if (match) {
      result.set(match[2], match[1].toLowerCase());
    }
  }
  return result;
}

function sha256(filePath) {
  const hash = createHash('sha256');
  hash.update(fs.readFileSync(filePath));
  return hash.digest('hex').toLowerCase();
}

function flattenSingleSubdir(destDir) {
  const entries = fs.readdirSync(destDir);
  if (entries.length !== 1) return;

  const subdir = path.join(destDir, entries[0]);
  if (!fs.statSync(subdir).isDirectory()) return;

  for (const child of fs.readdirSync(subdir)) {
    fs.renameSync(path.join(subdir, child), path.join(destDir, child));
  }
  fs.rmdirSync(subdir);
}

async function installLocalArchive() {
  const version = getChromiumVersion();
  const archiveName = getArchiveName();
  const releaseDir = path.join(downloadRoot, `chromium-v${version}`);
  const archivePath = path.join(releaseDir, archiveName);
  const checksumsPath = path.join(releaseDir, 'SHA256SUMS');
  const binaryDir = getBinaryDir(version);
  const binaryPath = getBinaryPath(version);

  if (!fs.existsSync(archivePath)) {
    console.log(`[cairn-cloak] Local CloakBrowser archive not found: ${archivePath}`);
    process.exit(LOCAL_ARCHIVE_MISSING_EXIT_CODE);
  }

  if (!fs.existsSync(checksumsPath)) {
    throw new Error(`Local CloakBrowser archive exists but SHA256SUMS is missing: ${checksumsPath}`);
  }

  const checksums = parseChecksums(fs.readFileSync(checksumsPath, 'utf8'));
  const expected = checksums.get(archiveName);
  if (!expected) {
    throw new Error(`SHA256SUMS has no entry for ${archiveName}`);
  }

  const actual = sha256(archivePath);
  if (actual !== expected) {
    throw new Error(
      `CloakBrowser archive checksum mismatch for ${archivePath}\n` +
      `  Expected: ${expected}\n` +
      `  Got:      ${actual}`
    );
  }
  console.log('[cairn-cloak] Local CloakBrowser archive checksum verified');

  fs.rmSync(binaryDir, { recursive: true, force: true });
  fs.mkdirSync(binaryDir, { recursive: true });
  await tarExtract({
    file: archivePath,
    cwd: binaryDir,
    strip: 0,
    filter: entryPath => {
      if (path.isAbsolute(entryPath) || entryPath.includes('..')) {
        console.warn(`[cairn-cloak] Skipping suspicious archive entry: ${entryPath}`);
        return false;
      }
      return true;
    },
  });
  flattenSingleSubdir(binaryDir);

  if (fs.existsSync(binaryPath)) {
    fs.chmodSync(binaryPath, 0o755);
  }
  if (!fs.existsSync(binaryPath)) {
    throw new Error(`CloakBrowser binary missing after local archive install: ${binaryPath}`);
  }

  console.log(`[cairn-cloak] Installed CloakBrowser from local archive to ${binaryDir}`);
  console.log(binaryPath);
}

installLocalArchive().catch(error => {
  console.error(error?.stack || error?.message || String(error));
  process.exit(1);
});
