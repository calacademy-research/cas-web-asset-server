"""
Command Line Interface for thumbnail pre-generation.
"""

import argparse
import logging
import sys
import urllib3
from typing import List, Optional

from .s3_config import S3Config
from .s3_client import S3Client
from .local_client import LocalConfig, LocalClient
from .thumbnail_generator import ThumbnailGenerator
from .scanner import Scanner
from .scanner_progress import ScannerProgress
from .generator import Generator
from .generation_progress import GenerationProgress
from .manifest import Manifest
from .reporter import Reporter


def setup_logging(verbose: bool) -> logging.Logger:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logging.getLogger('boto3').setLevel(logging.WARNING)
    logging.getLogger('botocore').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    return logging.getLogger('pregen')


def get_s3_config(args: argparse.Namespace) -> S3Config:
    """Get S3 configuration from environment and CLI overrides."""
    config = S3Config.from_env()
    
    if hasattr(args, 's3_endpoint') and args.s3_endpoint:
        config.endpoint = args.s3_endpoint
    if hasattr(args, 's3_bucket') and args.s3_bucket:
        config.bucket = args.s3_bucket
    if hasattr(args, 's3_prefix') and args.s3_prefix:
        config.prefix = args.s3_prefix
    if hasattr(args, 's3_access_key') and args.s3_access_key:
        config.access_key = args.s3_access_key
    if hasattr(args, 's3_secret_key') and args.s3_secret_key:
        config.secret_key = args.s3_secret_key
    
    return config


def get_local_config(args: argparse.Namespace) -> LocalConfig:
    """Get local configuration from CLI arguments."""
    prefix = getattr(args, 'local_prefix', None) or 'attachments'
    return LocalConfig(
        root_path=args.local_root,
        prefix=prefix
    )


def get_storage_client(args: argparse.Namespace, logger: logging.Logger):
    """
    Get appropriate storage client based on arguments.
    
    Returns:
        Tuple of (client, storage_type, storage_info)
        - storage_type: 'local' or 's3'
        - storage_info: dict with endpoint/root info for manifest
    """
    local_root = getattr(args, 'local_root', None)
    
    if local_root:
        config = get_local_config(args)
        errors = config.validate()
        if errors:
            for error in errors:
                logger.error(error)
            raise ValueError("Local configuration invalid")
        
        client = LocalClient(config, logger)
        storage_info = {
            'type': 'local',
            'root_path': config.root_path,
            'prefix': config.prefix,
        }
        return client, 'local', storage_info
    else:
        config = get_s3_config(args)
        errors = config.validate()
        if errors:
            for error in errors:
                logger.error(error)
            raise ValueError("S3 configuration invalid")
        
        client = S3Client(config, logger)
        storage_info = {
            'type': 's3',
            'endpoint': config.endpoint,
            'bucket': config.bucket,
            'prefix': config.prefix,
        }
        return client, 's3', storage_info


def add_storage_arguments(parser: argparse.ArgumentParser) -> None:
    """Add storage configuration arguments to a parser."""
    # Local storage options
    local_group = parser.add_argument_group('Local Storage')
    local_group.add_argument('--local-root', metavar='PATH',
                            help='Use local filesystem instead of S3 (e.g., /mnt/specify-assets)')
    local_group.add_argument('--local-prefix', default='attachments',
                            help='Prefix within local root (default: attachments)')
    
    # S3 storage options
    s3_group = parser.add_argument_group('S3 Storage')
    s3_group.add_argument('--s3-endpoint', help='Override S3_ENDPOINT')
    s3_group.add_argument('--s3-bucket', help='Override S3_BUCKET')
    s3_group.add_argument('--s3-prefix', help='Override S3_PREFIX')
    s3_group.add_argument('--s3-access-key', help='Override S3_ACCESS_KEY')
    s3_group.add_argument('--s3-secret-key', help='Override S3_SECRET_KEY')


def cmd_scan(args: argparse.Namespace) -> int:
    """Execute scan command (Phase 1)."""
    logger = setup_logging(args.verbose)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        client, storage_type, storage_info = get_storage_client(args, logger)
    except ValueError:
        return 1
    
    if storage_type == 'local':
        logger.info(f"Storage: Local filesystem")
        logger.info(f"Root: {storage_info['root_path']}")
        logger.info(f"Prefix: {storage_info['prefix']}")
    else:
        logger.info(f"Storage: S3")
        logger.info(f"Endpoint: {storage_info['endpoint']}")
        logger.info(f"Bucket: {storage_info['bucket']}/{storage_info['prefix']}")
    
    logger.info(f"Output: {args.output}")
    
    if args.limit:
        logger.info(f"Test mode: limiting to {args.limit} images")
    
    if args.show_files:
        logger.info("Show-files mode: will print each file")
    
    try:
        scanner = Scanner(client, logger)
        
        progress = None
        if not args.quiet:
            progress = ScannerProgress(
                show_files=args.show_files,
                logger=logger
            )
        
        collections = args.collection if hasattr(args, 'collection') and args.collection else None
        manifest = scanner.scan(
            collections=collections, 
            progress=progress,
            limit=args.limit
        )
        
        # Store storage info in manifest
        manifest.storage_type = storage_type
        if storage_type == 'local':
            manifest.local_root = storage_info['root_path']
            manifest.s3_endpoint = None
            manifest.s3_bucket = None
        
        manifest.save(args.output)
        logger.info(f"Manifest saved to: {args.output}")
        
        if not args.quiet and not args.show_files:
            print()
            reporter = Reporter()
            reporter.report_summary(manifest)
        
        return 0
        
    except Exception as e:
        logger.exception(f"Scan failed: {e}")
        return 1


def cmd_generate(args: argparse.Namespace) -> int:
    """Execute generate command (Phase 2)."""
    logger = setup_logging(args.verbose)
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    try:
        manifest = Manifest.load(args.manifest)
        logger.info(f"Loaded manifest: {args.manifest}")
        logger.info(f"  Created: {manifest.created_at}")
        logger.info(f"  Images: {manifest.total_images}")
        logger.info(f"  Missing thumbnails: {manifest.total_missing_thumbnails}")
    except FileNotFoundError:
        logger.error(f"Manifest not found: {args.manifest}")
        return 1
    except Exception as e:
        logger.error(f"Failed to load manifest: {e}")
        return 1
    
    if manifest.is_stale():
        age_hours = manifest.age_hours
        logger.warning(f"⚠️  Manifest is {age_hours:.1f} hours old!")
        if not args.force:
            logger.warning("Use --force to proceed anyway, or re-run scan first.")
            return 1
        logger.warning("Proceeding anyway due to --force flag.")
    
    # Determine storage type from manifest or CLI override
    local_root = getattr(args, 'local_root', None)
    manifest_is_local = getattr(manifest, 'storage_type', None) == 'local'
    
    if local_root:
        # CLI override - use local
        config = LocalConfig(
            root_path=local_root,
            prefix=getattr(args, 'local_prefix', None) or manifest.s3_prefix or 'attachments'
        )
        errors = config.validate()
        if errors:
            for error in errors:
                logger.error(error)
            return 1
        
        client = LocalClient(config, logger)
        logger.info(f"Storage: Local filesystem")
        logger.info(f"Root: {config.root_path}")
    elif manifest_is_local:
        # Manifest was from local scan
        local_root = getattr(manifest, 'local_root', None)
        if not local_root:
            logger.error("Manifest is local but missing local_root")
            return 1
        
        config = LocalConfig(
            root_path=local_root,
            prefix=manifest.s3_prefix or 'attachments'
        )
        errors = config.validate()
        if errors:
            for error in errors:
                logger.error(error)
            return 1
        
        client = LocalClient(config, logger)
        logger.info(f"Storage: Local filesystem (from manifest)")
        logger.info(f"Root: {config.root_path}")
    else:
        # S3 storage
        config = S3Config(
            endpoint=args.s3_endpoint or manifest.s3_endpoint,
            bucket=args.s3_bucket or manifest.s3_bucket,
            prefix=args.s3_prefix or manifest.s3_prefix,
            access_key=args.s3_access_key or S3Config.from_env().access_key,
            secret_key=args.s3_secret_key or S3Config.from_env().secret_key,
        )
        
        errors = config.validate()
        if errors:
            for error in errors:
                logger.error(error)
            return 1
        
        client = S3Client(config, logger)
        logger.info(f"Storage: S3")
        logger.info(f"Endpoint: {config.endpoint}")
    
    logger.info(f"Thumbnail size: {args.size}px")
    logger.info(f"Cadence: {args.cadence}s")
    
    if args.limit:
        logger.info(f"Test mode: limiting to {args.limit} thumbnails")
    
    if args.show_files:
        logger.info("Show-files mode: will print each file")
    
    try:
        thumb_gen = ThumbnailGenerator(args.size, logger=logger)
        generator = Generator(
            s3_client=client,  # Works with both S3Client and LocalClient
            thumbnail_generator=thumb_gen,
            cadence=args.cadence,
            dry_run=args.dry_run,
            logger=logger
        )
        
        progress = None
        if not args.quiet:
            progress = GenerationProgress(
                show_files=args.show_files,
                logger=logger
            )
        
        collections = args.collection if hasattr(args, 'collection') and args.collection else None
        stats = generator.generate_from_manifest(
            manifest=manifest,
            collections=collections,
            resume_from=args.resume,
            progress=progress,
            limit=args.limit
        )
        
        if not args.quiet:
            print()
            print(f"Generated: {stats.processed}")
            print(f"Errors: {stats.errors}")
            print(f"Time: {stats.elapsed_seconds:.1f}s")
            print(f"Rate: {stats.rate_per_minute:.1f}/min")
        
        return 0 if stats.errors == 0 else 1
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Generation failed: {e}")
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    """Execute report command."""
    logger = setup_logging(args.verbose)
    
    try:
        manifest = Manifest.load(args.manifest)
    except FileNotFoundError:
        logger.error(f"Manifest not found: {args.manifest}")
        return 1
    except Exception as e:
        logger.error(f"Failed to load manifest: {e}")
        return 1
    
    reporter = Reporter()
    collections = args.collection if hasattr(args, 'collection') and args.collection else None
    
    if args.type == 'summary':
        reporter.report_summary(manifest)
    elif args.type == 'detailed':
        reporter.report_detailed(manifest)
    elif args.type == 'plan':
        reporter.report_action_plan(manifest, args.size, args.cadence, collections)
    elif args.type == 'missing':
        reporter.report_missing_files(manifest, collections)
    elif args.type == 'sizes':
        reporter.report_thumbnail_sizes(manifest, collections, target_scale=args.size)
    
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog='pregen',
        description='Thumbnail pre-generation for cas-web-asset-server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Two-phase workflow:
  1. Scan:     python -m pregen scan --output manifest.json
  2. Report:   python -m pregen report --manifest manifest.json
  3. Generate: python -m pregen generate --manifest manifest.json

Storage options:
  Use --local-root for local filesystem, or S3 environment variables for S3.
  
Testing:
  Use --limit 3 to process only 3 images (works for both scan and generate)
"""
    )
    
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan storage and create manifest (Phase 1)')
    scan_parser.add_argument('-o', '--output', default='manifest.json', help='Output manifest file')
    scan_parser.add_argument('--collection', action='append', help='Collection(s) to scan')
    scan_parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    scan_parser.add_argument('--show-files', action='store_true', 
                            help='Print each file as scanned with thumbnail status')
    scan_parser.add_argument('--limit', type=int, metavar='N',
                            help='Limit to N images (for testing)')
    scan_parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    add_storage_arguments(scan_parser)
    
    # Generate command
    gen_parser = subparsers.add_parser('generate', help='Generate thumbnails from manifest (Phase 2)')
    gen_parser.add_argument('-m', '--manifest', required=True, help='Input manifest file')
    gen_parser.add_argument('-s', '--size', type=int, default=200, help='Thumbnail size (default: 200)')
    gen_parser.add_argument('-c', '--cadence', type=float, default=1.0, help='Seconds between images')
    gen_parser.add_argument('--collection', action='append', help='Collection(s) to process')
    gen_parser.add_argument('--resume', help='Resume from filename')
    gen_parser.add_argument('-n', '--dry-run', action='store_true', help='Show what would be done')
    gen_parser.add_argument('-f', '--force', action='store_true', help='Proceed even if manifest is stale')
    gen_parser.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    gen_parser.add_argument('--show-files', action='store_true',
                           help='Print each file as processed with result')
    gen_parser.add_argument('--limit', type=int, metavar='N',
                           help='Limit to N thumbnails (for testing)')
    gen_parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    add_storage_arguments(gen_parser)
    
    # Report command
    report_parser = subparsers.add_parser('report', help='Generate reports from manifest')
    report_parser.add_argument('-m', '--manifest', required=True, help='Input manifest file')
    report_parser.add_argument('-t', '--type', choices=['summary', 'detailed', 'plan', 'missing', 'sizes'],
                              default='summary', help='Report type')
    report_parser.add_argument('--collection', action='append', help='Collection(s) to include')
    report_parser.add_argument('-s', '--size', type=int, default=200, help='Thumbnail size for plan/sizes report')
    report_parser.add_argument('-c', '--cadence', type=float, default=1.0, help='Cadence for plan')
    report_parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    
    return parser


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)
    
    if not parsed_args.command:
        parser.print_help()
        return 1
    
    if parsed_args.command == 'scan':
        return cmd_scan(parsed_args)
    elif parsed_args.command == 'generate':
        return cmd_generate(parsed_args)
    elif parsed_args.command == 'report':
        return cmd_report(parsed_args)
    
    return 1
