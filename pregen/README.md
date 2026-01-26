# Thumbnail Pre-Generation Tool (pregen)

A two-phase thumbnail pre-generation system for the CAS Web Asset Server. Designed to handle millions of images efficiently by separating the scanning phase from the generation phase.

## Overview

The tool works in two phases:

1. **Scan Phase**: Inventories all original images and existing thumbnails, producing a manifest JSON file
2. **Generate Phase**: Reads the manifest and generates missing thumbnails at the requested size

**Supports both S3 and local filesystem storage.**

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Requirements

- Python 3.8+
- boto3 (S3 client) - only needed for S3 storage
- Pillow (image processing)

## Quick Start

### Using Local Filesystem

```bash
# Scan all collections
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets

# Review what will be generated
python -m pregen report -m manifest.json -t sizes -s 200

# Generate thumbnails
python -m pregen generate -m manifest.json -s 200 -c 0
```

### Using S3

```bash
# Configure S3 access
export S3_ENDPOINT="https://your-s3-endpoint:9000"
export S3_BUCKET="your-bucket"
export S3_PREFIX="attachments"
export S3_ACCESS_KEY="your-access-key"
export S3_SECRET_KEY="your-secret-key"

# Scan all collections
python -m pregen scan -o manifest.json

# Review what will be generated
python -m pregen report -m manifest.json -t sizes -s 200

# Generate thumbnails
python -m pregen generate -m manifest.json -s 200 -c 0.5
```

## Storage Options

### Local Filesystem

Use `--local-root` to scan and generate from local filesystem:

```bash
# Scan local storage
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets

# With custom prefix (default: attachments)
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets --local-prefix attachments
```

Expected directory structure:
```
/mnt/specify-assets/
└── attachments/
    ├── botany/
    │   ├── originals/
    │   │   └── 00/00/uuid.jpg
    │   └── thumbnails/
    │       └── 00/00/uuid_200.jpg
    ├── ichthyology/
    │   ├── originals/
    │   └── thumbnails/
    └── iz/
        ├── originals/
        └── thumbnails/
```

### S3 Storage

Configure via environment variables or CLI arguments:

```bash
# Environment variables
export S3_ENDPOINT="https://your-s3-endpoint:9000"
export S3_BUCKET="your-bucket"
export S3_PREFIX="attachments"
export S3_ACCESS_KEY="your-access-key"
export S3_SECRET_KEY="your-secret-key"

# Or CLI arguments
python -m pregen scan -o manifest.json \
    --s3-endpoint https://your-s3-endpoint:9000 \
    --s3-bucket your-bucket \
    --s3-prefix attachments
```

## Commands

### scan - Phase 1: Create Manifest

Scans storage to enumerate all original images and their existing thumbnails.

```bash
python -m pregen scan [OPTIONS]
```

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--output` | `-o` | `manifest.json` | Output manifest file path |
| `--collection` | | all | Collection(s) to scan (can be repeated) |
| `--quiet` | `-q` | false | Suppress progress output |
| `--show-files` | | false | Print each file as scanned with thumbnail status |
| `--limit` | | none | Limit to N images (for testing) |
| `--verbose` | `-v` | false | Enable verbose/debug logging |
| `--local-root` | | none | Use local filesystem at this path |
| `--local-prefix` | | `attachments` | Prefix within local root |
| `--s3-endpoint` | | env | Override S3_ENDPOINT |
| `--s3-bucket` | | env | Override S3_BUCKET |
| `--s3-prefix` | | env | Override S3_PREFIX |
| `--s3-access-key` | | env | Override S3_ACCESS_KEY |
| `--s3-secret-key` | | env | Override S3_SECRET_KEY |

#### Examples

**Local Filesystem:**
```bash
# Scan all collections
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets

# Scan specific collection
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets --collection ichthyology

# Scan multiple collections
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets --collection botany --collection ichthyology

# Quick test scan (3 images only, verbose)
python -m pregen scan -o test.json --limit 3 --show-files -v --local-root /mnt/specify-assets
```

**S3 Storage:**
```bash
# Scan all collections (uses environment variables)
python -m pregen scan -o manifest.json

# Scan with explicit S3 arguments
python -m pregen scan -o manifest.json \
    --s3-endpoint https://your-s3-endpoint:9000 \
    --s3-bucket your-bucket \
    --s3-prefix attachments

# Scan specific collection
python -m pregen scan -o manifest.json --collection ichthyology

# Scan multiple collections
python -m pregen scan -o manifest.json --collection botany --collection ichthyology

# Quick test scan (3 images only, verbose)
python -m pregen scan -o test.json --limit 3 --show-files -v
```

---

### generate - Phase 2: Generate Thumbnails

Generates thumbnails for images that are missing them at the specified size.

```bash
python -m pregen generate -m MANIFEST [OPTIONS]
```

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--manifest` | `-m` | required | Input manifest file |
| `--size` | `-s` | `200` | Thumbnail max dimension in pixels |
| `--cadence` | `-c` | `1.0` | Seconds to wait between images (throttling) |
| `--collection` | | all | Collection(s) to process (can be repeated) |
| `--resume` | | none | Resume from filename (alphabetically) |
| `--dry-run` | `-n` | false | Show what would be done without generating |
| `--force` | `-f` | false | Proceed even if manifest is older than 24 hours |
| `--quiet` | `-q` | false | Suppress progress output |
| `--show-files` | | false | Print each file as processed with result |
| `--limit` | | none | Limit to N thumbnails (for testing) |
| `--verbose` | `-v` | false | Enable verbose/debug logging |
| `--local-root` | | manifest | Override local storage root |
| `--local-prefix` | | manifest | Override local prefix |
| `--s3-endpoint` | | manifest | Override S3_ENDPOINT |
| `--s3-bucket` | | manifest | Override S3_BUCKET |
| `--s3-prefix` | | manifest | Override S3_PREFIX |
| `--s3-access-key` | | env | Override S3_ACCESS_KEY |
| `--s3-secret-key` | | env | Override S3_SECRET_KEY |

#### Examples

The manifest remembers the storage type (local or S3) from the scan phase. Most commands work the same regardless of storage:

```bash
# Generate 200px thumbnails (manifest knows storage type)
python -m pregen generate -m manifest.json

# Generate custom size
python -m pregen generate -m manifest.json -s 400

# Generate with no delay (faster, recommended for local)
python -m pregen generate -m manifest.json -c 0

# Generate with throttling (recommended for S3)
python -m pregen generate -m manifest.json -c 0.5

# Dry run - see what would be generated
python -m pregen generate -m manifest.json --dry-run

# Test run - generate only 3 thumbnails with full verbosity
python -m pregen generate -m manifest.json -s 123 --limit 3 --show-files -v

# Test dry run
python -m pregen generate -m manifest.json -s 123 --limit 3 --show-files -v --dry-run
```

**Overriding storage location:**
```bash
# Override local root (if manifest has different path)
python -m pregen generate -m manifest.json --local-root /new/path

# Override S3 endpoint
python -m pregen generate -m manifest.json --s3-endpoint https://new-endpoint:9000
```

---

### report - Generate Reports

Generates various reports from a manifest file.

```bash
python -m pregen report -m MANIFEST [OPTIONS]
```

#### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--manifest` | `-m` | required | Input manifest file |
| `--type` | `-t` | `summary` | Report type (see below) |
| `--collection` | | all | Collection(s) to include (can be repeated) |
| `--size` | `-s` | `200` | Thumbnail size for plan/sizes reports |
| `--cadence` | `-c` | `1.0` | Cadence for time estimates in plan report |
| `--verbose` | `-v` | false | Enable verbose logging |

#### Report Types

| Type | Description |
|------|-------------|
| `summary` | Overview of images and thumbnail coverage per collection |
| `detailed` | Summary plus storage statistics (original vs thumbnail sizes) |
| `plan` | Action plan showing what would be generated and time estimates |
| `missing` | List of files missing thumbnails (first 100 by default) |
| `sizes` | **Detailed breakdown of thumbnail sizes per collection** |

#### Examples

```bash
# Basic summary
python -m pregen report -m manifest.json

# Thumbnail sizes breakdown (most useful)
python -m pregen report -m manifest.json -t sizes -s 200

# Action plan with time estimates
python -m pregen report -m manifest.json -t plan -s 200 -c 0.5
```

---

## Common Workflows

### Testing Before Full Run

**Local Filesystem:**
```bash
# Test scan with 3 images (from all collections)
python -m pregen scan -o test.json --limit 3 --show-files -v --local-root /mnt/specify-assets

# Review the test manifest
cat test.json

# Test generation (dry run)
python -m pregen generate -m test.json -s 200 --dry-run --show-files -v

# Test actual generation of 3 thumbnails
python -m pregen generate -m test.json -s 200 --limit 3 --show-files -v -c 0
```

**S3 Storage:**
```bash
# Test scan with 3 images (from all collections)
python -m pregen scan -o test.json --limit 3 --show-files -v

# Review the test manifest
cat test.json

# Test generation (dry run)
python -m pregen generate -m test.json -s 200 --dry-run --show-files -v

# Test actual generation of 3 thumbnails (with throttling)
python -m pregen generate -m test.json -s 200 --limit 3 --show-files -v -c 0.5
```

### Generate Multiple Sizes

**Local Filesystem:**
```bash
# Scan all collections once
python -m pregen scan -o manifest.json --local-root /mnt/specify-assets

# Generate standard size (200px)
python -m pregen generate -m manifest.json -s 200 -c 0

# Generate larger size (400px)
python -m pregen generate -m manifest.json -s 400 -c 0
```

**S3 Storage:**
```bash
# Scan all collections once
python -m pregen scan -o manifest.json

# Generate standard size (200px, with throttling)
python -m pregen generate -m manifest.json -s 200 -c 0.5

# Generate larger size (400px)
python -m pregen generate -m manifest.json -s 400 -c 0.5
```

### Per-Collection Management

**Local Filesystem:**
```bash
# Scan only ichthyology
python -m pregen scan -o manifest-ich.json --local-root /mnt/specify-assets --collection ichthyology

# Check status
python -m pregen report -m manifest-ich.json -t sizes -s 200

# Generate for ichthyology only
python -m pregen generate -m manifest-ich.json -s 200 -c 0
```

**S3 Storage:**
```bash
# Scan only ichthyology
python -m pregen scan -o manifest-ich.json --collection ichthyology

# Check status
python -m pregen report -m manifest-ich.json -t sizes -s 200

# Generate for ichthyology only
python -m pregen generate -m manifest-ich.json -s 200 -c 0.5
```

### Full Production Workflow (Local)

```bash
# 1. Full scan (all collections)
python -m pregen scan -o manifest-$(date +%Y%m%d).json --local-root /mnt/specify-assets

# 2. Review thumbnail coverage
python -m pregen report -m manifest-*.json -t sizes -s 200

# 3. Dry-run to verify
python -m pregen generate -m manifest-*.json -s 200 --dry-run --limit 10 --show-files

# 4. Generate all thumbnails (no throttling for local storage)
python -m pregen generate -m manifest-*.json -s 200 -c 0

# 5. If interrupted, resume
python -m pregen generate -m manifest-*.json -s 200 -c 0 --resume "last-processed-file.jpg"
```

### Full Production Workflow (S3)

```bash
# 1. Full scan (all collections, uses S3 environment variables)
python -m pregen scan -o manifest-$(date +%Y%m%d).json

# 2. Review thumbnail coverage
python -m pregen report -m manifest-*.json -t sizes -s 200

# 3. Dry-run to verify
python -m pregen generate -m manifest-*.json -s 200 --dry-run --limit 10 --show-files

# 4. Generate all thumbnails (with throttling for S3)
python -m pregen generate -m manifest-*.json -s 200 -c 0.5

# 5. If interrupted, resume
python -m pregen generate -m manifest-*.json -s 200 -c 0.5 --resume "last-processed-file.jpg"
```

---

## Manifest Format

The manifest is a JSON file containing:

```json
{
  "created_at": "2026-01-22T11:30:00.000000",
  "storage_type": "local",
  "local_root": "/mnt/specify-assets",
  "s3_endpoint": null,
  "s3_bucket": null,
  "s3_prefix": "attachments",
  "collections": ["botany", "ichthyology"],
  "collection_stats": {
    "ichthyology": {
      "name": "ichthyology",
      "total_images": 8828,
      "with_thumbnails": 8500,
      "missing_thumbnails": 328,
      "total_original_bytes": 19105404890,
      "total_thumbnail_bytes": 245200000
    }
  },
  "records": [
    {
      "original_key": "attachments/ichthyology/originals/00/00/uuid.jpg",
      "original_size": 5000000,
      "original_modified": "2025-01-07T01:56:26+00:00",
      "base_thumbnail_key": "attachments/ichthyology/thumbnails/00/00/uuid.jpg",
      "collection": "ichthyology",
      "filename": "uuid.jpg",
      "thumbnails": {
        "200": {
          "scale": 200,
          "key": "attachments/ichthyology/thumbnails/00/00/uuid_200.jpg",
          "size": 28582,
          "modified": "2025-08-13T03:12:17+00:00"
        }
      }
    }
  ],
  "scan_duration_seconds": 1234.5
}
```

For S3 storage, the manifest will have:
- `"storage_type": "s3"`
- `"s3_endpoint": "https://your-endpoint:9000"`
- `"s3_bucket": "your-bucket"`
- `"local_root": null`

---

## Thumbnail Naming Convention

Thumbnails are stored with the scale encoded in the filename:

```
Original:  {prefix}/{collection}/originals/{hash1}/{hash2}/{uuid}.jpg
Thumbnail: {prefix}/{collection}/thumbnails/{hash1}/{hash2}/{uuid}_{scale}.jpg
```

Examples:
- `uuid_200.jpg` - 200px max dimension
- `uuid_400.jpg` - 400px max dimension

The scale represents the maximum dimension (width or height). Aspect ratio is preserved.

---

## Performance Tips

### Local Filesystem
- Use `-c 0` (no cadence) for maximum speed
- Local I/O is typically not the bottleneck
- Consider running multiple collections in parallel

### S3 Storage
- Use `-c 0.1` to `-c 0.5` to avoid overwhelming the server
- Network latency is the main bottleneck
- Consider running during off-peak hours

### Large Collections
- Botany: ~1.3M images - scan takes ~30-60 minutes
- Use `--limit` for testing before full runs
- Manifest files can be large (100MB+ for millions of images)

---

## Troubleshooting

### "Manifest is stale" Warning

The manifest is older than 24 hours. Either:
- Re-run scan: `python -m pregen scan -o new-manifest.json --local-root /mnt/specify-assets`
- Force continue: `python -m pregen generate -m old-manifest.json --force`

### Local Path Not Found

Check that:
1. `--local-root` points to the correct directory
2. The prefix directory exists (e.g., `/mnt/specify-assets/attachments/`)
3. Collections have `originals/` and `thumbnails/` subdirectories

### No Thumbnails Found

Ensure thumbnails use the naming convention:
- `{uuid}_{scale}.{ext}` format (e.g., `abc123_200.jpg`)

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (see logs) |
| 130 | Interrupted (Ctrl+C) |
