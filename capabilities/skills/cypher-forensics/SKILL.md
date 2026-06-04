---
name: cypher-forensics
description: Digital forensics methodology covering memory analysis (Volatility3), disk forensics, file carving and recovery, steganography detection, network traffic analysis, log analysis, and timeline reconstruction.
version: 0.1.0
finding_types: [FORENSIC_ARTIFACT, BINARY_FINDING, EXPLOIT_RESULT]
destructiveness: low
tags: [ctf, forensics, memory, stego, network, file-carving]
---

# Cypher Forensics Skill

Use this skill for CTF forensics challenges, memory dump analysis, disk image investigation, network packet capture analysis, steganography challenges, and log-based investigations.

## Memory forensics (Volatility3)

```bash
# Image info
vol -f memory.dump windows.info
vol -f memory.dump linux.info

# Process listing
vol -f memory.dump windows.pslist
vol -f memory.dump windows.pstree
vol -f memory.dump linux.pslist

# Command history
vol -f memory.dump windows.cmdline
vol -f memory.dump linux.bash

# Network connections
vol -f memory.dump windows.netstat
vol -f memory.dump linux.sockstat

# File scan (recover files from memory)
vol -f memory.dump windows.filescan
vol -f memory.dump linux.filescan
vol -f memory.dump windows.dumpfiles --pid <pid> --virtaddr <offset>

# Registry (Windows)
vol -f memory.dump windows.registry.hivelist
vol -f memory.dump windows.registry.printkey --key "Software\Microsoft\Windows\CurrentVersion"

# Process dump
vol -f memory.dump windows.memmap --pid <pid> --dump

# Malware detection
vol -f memory.dump windows.malfind
vol -f memory.dump windows.dlllist --pid <pid>

# Password / credential extraction
vol -f memory.dump windows.hashdump
vol -f memory.dump windows.lsadump
vol -f memory.dump linux.elfs
```

### Common CTF memory patterns
- Flag in process memory: dump suspicious processes, `strings` the dumps
- Flag in command line: `windows.cmdline` / `linux.bash` / `linux.psaux`
- Flag in environment: `linux.environ` → look for env vars
- Flag in clipboard: `windows.clipboard`
- Flag in Notepad/editor: `windows.notepad` or dump process
- Malicious process hiding flag: `windows.malfind` → dump and analyze

## Disk forensics

### Image analysis
```bash
fdisk -l disk.img                  # partition table
mmls disk.img                      # volume layout (sleuthkit)
fls -o <offset> disk.img           # list files (sleuthkit)
icat -o <offset> disk.img <inode>  # extract file
fsstat -o <offset> disk.img        # filesystem info
```

### Deleted file recovery
```bash
# sleuthkit / autopsy
fls -d -r -o <offset> disk.img     # list deleted files
icat -o <offset> disk.img <inode>  # recover deleted (unallocated) file content
# extundelete (ext3/4), testdisk, photorec (file carving)
# foremost / scalpel for raw carving
foremost -t all -o output/ disk.img
```

### Common CTF disk patterns
- Flag in a hidden file: `find`, `ls -la`, check all directories
- Flag in deleted file: recover with `fls -d` + `icat` or `extundelete`
- Flag in alternate data stream (NTFS): `getfattr`, `icat` with attribute
- Flag in file slack space: `blkcat` free blocks, `strings` on them
- Flag in MFT $Data attribute (NTFS): parse MFT entry

## Steganography

### Image stego
```bash
# Metadata
exiftool image.jpg

# LSB stego (least significant bit)
zsteg image.png                    # PNG/BMP LSB detection
stegsolve image.png                # GUI: extract bit planes, XOR, color filters
steghide extract -sf image.jpg     # steghide-embedded data

# JPEG-specific
jsteg image.jpg                    # JPEG DCT coefficient stego
stegdetect -t all image.jpg        # Detect stego tool used
```

### Audio stego
```bash
# Spectrogram (hide data in frequency domain)
sox audio.wav -n spectrogram       # View spectrogram
audacity → Spectrogram view        # GUI: check for hidden text/images in frequencies

# LSB audio
# Python: wave module → read LSB of each sample → decode
```

### Other stego
- **PDF**: layers, annotations, hidden text behind images, incremental updates
- **ZIP**: appended data after ZIP EOCD (End of Central Directory) record
- **PNG**: extra chunks (tEXt, zTXt), hidden data between IDAT chunks
- **WAV/MP3**: tags, trailing data after audio stream
- **Video frames**: hidden frames, pixel-level LSB in specific frames
- **Whitespace stego**: tabs/spaces encoding, zero-width Unicode characters

### CTF stego checklist
1. `strings <file> | grep -i flag` — quick win
2. `exiftool <file>` — metadata flag
3. `binwalk <file>` — embedded/appended files
4. `zsteg <file>` (PNG/BMP) — LSB detection
5. `steghide extract -sf <file>` — try empty passphrase
6. Check trailing data: `tail -c +<expected_size> <file> | xxd`
7. Check file format anomalies: extra bytes between chunks
8. Color channel manipulation: XOR R/G/B planes, extract single channel

## Network forensics (PCAP analysis)

```bash
# Wireshark / tshark
tshark -r capture.pcap -Y "http" -T fields -e http.request.uri
tshark -r capture.pcap -Y "dns" -T fields -e dns.qry.name

# Extract files from HTTP
# Wireshark: File → Export Objects → HTTP

# Extract TCP stream data
tshark -r capture.pcap -Y "tcp.stream eq 0" -T fields -e data

# USB captures
tshark -r usb.pcap -Y "usb.capdata" -T fields -e usb.capdata
# Decode USB HID keyboard data → keystrokes
```

## Tools reference

| Category | Tools |
|----------|-------|
| Memory | volatility3, volatility2 (old plugins), rekall |
| Disk | sleuthkit (fls, icat, mmls), autopsy, testdisk, photorec, foremost |
| Stego | zsteg, stegsolve, steghide, stegdetect, exiftool, binwalk, strings |
| Network | tshark, wireshark, tcpdump, tcpflow, networkminer |
| Hash/password | hashcat, john, fcrackzip, pdfcrack, zip2john, rar2john |
| General | hexdump/xxd, file, strings, grep, CyberChef |

## Evidence rules

- Save extracted/recovered data to `/mnt/project/vuln-research/`.
- Save screenshots of key analysis steps (spectrogram, hex dump, memory region) to `/mnt/project/recon/`.
- Document the forensic workflow: tool used, parameters, extracted artifact, and interpretation.
- For stego, save both the original and extracted/decoded files.

## Prefix examples

```text
[cypher:finding type=FORENSIC_ARTIFACT confidence=0.95 severity=info tags=ctf,forensics,memory artifacts=/mnt/project/vuln-research/memdump-analysis.txt cleanup=none] Volatility3 windows.pslist reveals suspicious `flag_reader.exe` process (PID 4588) — memory dump pending.
```

```text
[cypher:finding type=EXPLOIT_RESULT confidence=1.0 severity=info tags=ctf,forensics,stego artifacts=/mnt/project/exploit/solve.py cleanup=none] flag{LSB_h1d3_1n_pl41n_s1ght} extracted from PNG using zsteg — LSB encoded in blue channel, bit 0.
```

## Common stego false negatives

- Some stego tools require a passphrase (steghide, outguess). Try empty password, challenge name, common passwords.
- LSB is not always sequential — sometimes the encoding pattern is geometric, uses PRNG for position selection, or skips bits.
- Multi-layer: data is encoded in stego, which is then compressed and encoded again.
