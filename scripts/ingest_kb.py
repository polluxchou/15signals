"""
ingest_kb.py — Parse mentor KB markdown files, generate Voyage embeddings,
write to Postgres `mentor_kb_chunks`.

Usage:
    python ingest_kb.py [options]

Options:
    --mentor {freud,weber,marx,all}   default: all
    --kb-dir PATH                     default: ../mentor_kb
    --dry-run                         Parse + embed, skip DB write
    --no-embed                        Skip embedding (parse only; useful for grammar checks)
    --batch-size N                    Voyage batch size, default: 16
    --verbose                         Debug logging

Required env vars (load from .env at script dir or current dir):
    DATABASE_URL     postgres://user:pass@host:port/db
    VOYAGE_API_KEY   Voyage AI key
    VOYAGE_MODEL     optional, default: voyage-3 (1024 dims, matches schema)

Idempotency strategy:
    For each (mentor_id, kb_version) pair found in the markdown, soft-delete
    all existing rows (set deleted_at = now()), then insert the fresh set.
    Re-running the script bumps deleted_at on prior versions but preserves
    history. To purge soft-deleted rows, run a separate cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest_kb")

# -----------------------------------------------------------------------------
# Parsing
# -----------------------------------------------------------------------------

# Matches: ### [concept] · Verdrängung · 压抑
CHUNK_HEADER_RE = re.compile(
    r"^###\s+\[(?P<chunk_type>\w+)\]\s+·\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)

# Matches the first ```yaml ... ``` block in a chunk body
YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)\n```", re.DOTALL)

# Matches the "**版本：** kb-xxx-v0.1" header line
KB_VERSION_RE = re.compile(r"\*\*版本：\*\*\s*(\S+)")

VALID_CHUNK_TYPES = {
    "concept",
    "voice_example",
    "opening_template",
    "signal_mapping",
    "forbidden_move",
    "biographical",
}


@dataclass
class Chunk:
    mentor_id: str
    chunk_type: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    related_signals: list[str] = field(default_factory=list)
    template_meta: dict[str, Any] | None = None
    source_citation: str | None = None
    kb_version: str = "v0.1"
    embedding: list[float] | None = None
    source_file: str = ""

    @property
    def fingerprint(self) -> str:
        """Stable hash of content; useful for change detection."""
        payload = json.dumps(
            {
                "mentor": self.mentor_id,
                "type": self.chunk_type,
                "title": self.title,
                "content": self.content,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    def embedding_text(self) -> str:
        """Composite text used for embedding generation."""
        # Title carries strong signal — prepend it to content
        return f"{self.title}\n\n{self.content}"


def parse_markdown(path: Path) -> list[Chunk]:
    import yaml  # imported here so --help works without the dep

    text = path.read_text(encoding="utf-8")

    version_match = KB_VERSION_RE.search(text)
    kb_version = version_match.group(1) if version_match else "v0.1"

    headers = list(CHUNK_HEADER_RE.finditer(text))
    if not headers:
        log.warning("No chunk headers found in %s", path.name)
        return []

    chunks: list[Chunk] = []
    skipped = 0

    for i, h in enumerate(headers):
        header_chunk_type = h.group("chunk_type")
        title = h.group("title").strip()

        body_start = h.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end]

        yaml_match = YAML_BLOCK_RE.search(body)
        if not yaml_match:
            log.warning("  skip (no yaml block): %s · %s", header_chunk_type, title)
            skipped += 1
            continue

        try:
            metadata = yaml.safe_load(yaml_match.group(1)) or {}
        except yaml.YAMLError as e:
            log.warning("  skip (yaml error): %s · %s — %s", header_chunk_type, title, e)
            skipped += 1
            continue

        content = body[yaml_match.end():].strip()
        # Strip a trailing horizontal rule (separator before next chunk)
        content = re.sub(r"\n+---\s*$", "", content).strip()

        # Resolve chunk_type: prefer YAML, fallback to header
        chunk_type = metadata.get("chunk_type", header_chunk_type)
        if chunk_type not in VALID_CHUNK_TYPES:
            log.warning(
                "  skip (invalid chunk_type %r): %s · %s",
                chunk_type, header_chunk_type, title,
            )
            skipped += 1
            continue

        mentor_id = metadata.get("mentor_id", "")
        if not mentor_id:
            log.warning("  skip (no mentor_id): %s · %s", chunk_type, title)
            skipped += 1
            continue

        chunk = Chunk(
            mentor_id=mentor_id,
            chunk_type=chunk_type,
            title=title,
            content=content,
            tags=metadata.get("tags") or [],
            related_signals=metadata.get("related_signals") or [],
            template_meta=metadata.get("template_meta"),
            source_citation=metadata.get("source_citation"),
            kb_version=kb_version,
            source_file=path.name,
        )

        if not content:
            log.warning("  warn (empty content): %s · %s", chunk_type, title)

        chunks.append(chunk)

    log.info(
        "  parsed %d chunks from %s (version=%s, skipped=%d)",
        len(chunks), path.name, kb_version, skipped,
    )
    return chunks


# -----------------------------------------------------------------------------
# Embedding
# -----------------------------------------------------------------------------

def embed_chunks(
    chunks: list[Chunk],
    model: str,
    batch_size: int = 16,
    throttle_seconds: float = 0,
) -> None:
    """Generate embeddings in-place. Batches + retries + optional throttle."""
    import voyageai

    if not chunks:
        return

    client = voyageai.Client()  # reads VOYAGE_API_KEY from env
    total = len(chunks)
    n_batches = (total + batch_size - 1) // batch_size
    eta_sec = throttle_seconds * (n_batches - 1) if throttle_seconds > 0 else 0
    log.info(
        "Embedding %d chunks (%d batches) with model=%s, batch_size=%d, throttle=%ss%s",
        total, n_batches, model, batch_size, throttle_seconds,
        f"  [ETA ~{int(eta_sec)}s]" if eta_sec else "",
    )

    for i, start in enumerate(range(0, total, batch_size)):
        # Throttle BEFORE each request except the first
        if i > 0 and throttle_seconds > 0:
            time.sleep(throttle_seconds)

        batch = chunks[start:start + batch_size]
        texts = [c.embedding_text() for c in batch]

        for attempt in range(3):
            try:
                result = client.embed(
                    texts,
                    model=model,
                    input_type="document",
                )
                for chunk, vec in zip(batch, result.embeddings):
                    chunk.embedding = vec
                log.info(
                    "  embedded %d–%d / %d  (batch %d/%d, tokens: %d)",
                    start + 1, start + len(batch), total,
                    i + 1, n_batches,
                    getattr(result, "total_tokens", -1),
                )
                break
            except Exception as e:
                if attempt == 2:
                    log.error("Embedding failed after 3 attempts: %s", e)
                    raise
                # If rate-limited, back off longer
                msg = str(e)
                if "rate" in msg.lower() or "RPM" in msg:
                    wait = max(throttle_seconds, 25) * (attempt + 1)
                else:
                    wait = 2 ** attempt
                log.warning(
                    "  embedding error (attempt %d/3), retrying in %ds: %s",
                    attempt + 1, wait, msg[:120],
                )
                time.sleep(wait)


# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------

def write_chunks(db_url: str, chunks: list[Chunk]) -> None:
    """Soft-delete prior rows per (mentor_id, kb_version), insert fresh batch."""
    import psycopg
    from pgvector.psycopg import register_vector

    if not chunks:
        return

    # Group by (mentor, version) for the soft-delete scope
    groups: dict[tuple[str, str], list[Chunk]] = {}
    for c in chunks:
        groups.setdefault((c.mentor_id, c.kb_version), []).append(c)

    with psycopg.connect(db_url) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for (mentor_id, kb_version), group in groups.items():
                cur.execute(
                    """
                    UPDATE mentor_kb_chunks
                    SET deleted_at = now()
                    WHERE mentor_id = %s
                      AND kb_version = %s
                      AND deleted_at IS NULL
                    """,
                    (mentor_id, kb_version),
                )
                log.info(
                    "  soft-deleted %d existing rows for (%s, %s)",
                    cur.rowcount, mentor_id, kb_version,
                )

                inserted = 0
                for c in group:
                    cur.execute(
                        """
                        INSERT INTO mentor_kb_chunks (
                            mentor_id, chunk_type, title, content, embedding,
                            tags, related_signals, template_meta, source_citation, kb_version
                        ) VALUES (
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            c.mentor_id,
                            c.chunk_type,
                            c.title,
                            c.content,
                            c.embedding,
                            c.tags,
                            c.related_signals,
                            json.dumps(c.template_meta, ensure_ascii=False)
                                if c.template_meta is not None else None,
                            c.source_citation,
                            c.kb_version,
                        ),
                    )
                    inserted += 1
                log.info("  inserted %d rows for (%s, %s)", inserted, mentor_id, kb_version)
        conn.commit()


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def load_env() -> None:
    """Load .env from script dir or current dir (script dir takes precedence)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return  # silently skip; user can set env vars directly

    script_dir_env = Path(__file__).parent / ".env"
    if script_dir_env.exists():
        load_dotenv(script_dir_env)
    project_env = Path(__file__).parent.parent / ".env"
    if project_env.exists():
        load_dotenv(project_env)
    load_dotenv()  # cwd fallback


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest mentor KB markdown into Postgres mentor_kb_chunks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mentor", choices=["freud", "weber", "marx", "all"], default="all",
        help="Which mentor's KB to ingest (default: all)",
    )
    parser.add_argument(
        "--kb-dir", type=Path,
        default=Path(__file__).parent.parent / "mentor_kb",
        help="Path to mentor_kb directory",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse + embed, skip DB write")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding (parse only)")
    parser.add_argument("--batch-size", type=int, default=16, help="Embedding batch size")
    parser.add_argument(
        "--throttle-seconds", type=float, default=0,
        help="Sleep this many seconds between embed batches (for free-tier rate limits, e.g. 22)",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.verbose:
        log.setLevel(logging.DEBUG)

    load_env()

    # Determine target files
    if args.mentor == "all":
        targets = ["freud.md", "weber.md", "marx.md"]
    else:
        targets = [f"{args.mentor}.md"]

    paths = [args.kb_dir / t for t in targets]
    for p in paths:
        if not p.exists():
            log.error("File not found: %s", p)
            return 1

    # 1. Parse
    log.info("Parsing %d file(s) from %s", len(paths), args.kb_dir)
    all_chunks: list[Chunk] = []
    for p in paths:
        all_chunks.extend(parse_markdown(p))

    if not all_chunks:
        log.error("No chunks parsed. Aborting.")
        return 1

    # Sanity report
    by_type: dict[str, int] = {}
    by_mentor: dict[str, int] = {}
    for c in all_chunks:
        by_type[c.chunk_type] = by_type.get(c.chunk_type, 0) + 1
        by_mentor[c.mentor_id] = by_mentor.get(c.mentor_id, 0) + 1
    log.info("Total chunks: %d", len(all_chunks))
    log.info("  by type:   %s", by_type)
    log.info("  by mentor: %s", by_mentor)

    # 2. Embed
    if args.no_embed:
        log.warning("Skipping embedding (--no-embed). DB rows will have NULL embedding.")
    else:
        if not os.getenv("VOYAGE_API_KEY"):
            log.error("VOYAGE_API_KEY not set in environment or .env")
            return 1
        model = os.getenv("VOYAGE_MODEL", "voyage-3")
        embed_chunks(
            all_chunks,
            model=model,
            batch_size=args.batch_size,
            throttle_seconds=args.throttle_seconds,
        )

    # 3. Write
    if args.dry_run:
        log.info("Dry run — skipping DB write.")
        sample = all_chunks[0]
        log.info(
            "Sample chunk: [%s] %s · %s (%d chars, embedding=%s)",
            sample.chunk_type, sample.mentor_id, sample.title,
            len(sample.content),
            f"dim={len(sample.embedding)}" if sample.embedding else "none",
        )
        return 0

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set in environment or .env")
        return 1

    log.info("Writing to database...")
    write_chunks(db_url, all_chunks)

    log.info("Done. %d chunks ingested.", len(all_chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
