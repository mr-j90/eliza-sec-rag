"""The Qdrant collection: one collection, named `dense` + `sparse` vectors.

SPEC §2 puts both vectors in the *same* collection so a hybrid query is one round trip with
no second store to keep in sync.

Run directly to build the index:

    uv run python -m src.index            # the seed filing
    uv run python -m src.index --all      # every filing in the corpus
"""

from __future__ import annotations

import sys
import uuid

from qdrant_client import QdrantClient, models

from src.chunks import Chunk, embedding_text
from src.config import DENSE_DIM, SEED_FILING, settings
from src.embed import dense_vectors, sparse_vectors
from src.ingest import chunk_filing

UPSERT_BATCH = 128


def client() -> QdrantClient:
    return QdrantClient(url=settings().qdrant_url)


def qdrant_reachable() -> bool:
    try:
        client().get_collections()
        return True
    except Exception:
        return False


class WrongInstance(RuntimeError):
    """The Qdrant we reached is holding somebody else's data.

    Guard against the silent failure `.eng/config.md` records: a client pointed at a port
    another project owns connects happily and creates its collection inside a stranger's
    instance. Nothing errors; the data is simply in the wrong place, and you find out much
    later. Refusing to write is the cheap version of finding out now.
    """


def _assert_ours(qdrant: QdrantClient) -> None:
    existing = {c.name for c in qdrant.get_collections().collections}
    strangers = existing - {settings().collection}
    if strangers:
        raise WrongInstance(
            f"{settings().qdrant_url} holds collections this project did not create: "
            f"{sorted(strangers)}. Refusing to write — check QDRANT_URL points at our own "
            f"compose service (default {settings().qdrant_url}), not another project's Qdrant."
        )


def ensure_collection(*, recreate: bool = False) -> None:
    qdrant = client()
    _assert_ours(qdrant)

    name = settings().collection
    if recreate and qdrant.collection_exists(name):
        qdrant.delete_collection(name)

    if not qdrant.collection_exists(name):
        qdrant.create_collection(
            collection_name=name,
            vectors_config={
                "dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )
        # Entry 5 filters by these; an index on the payload keys keeps that cheap once the
        # collection holds 30k points rather than 78.
        for field in ("ticker", "form_type", "fiscal_year", "item_section"):
            qdrant.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD
                if field != "fiscal_year"
                else models.PayloadSchemaType.INTEGER,
            )


def _point(chunk: Chunk, dense: list[float], sparse: models.SparseVector) -> models.PointStruct:
    return models.PointStruct(
        # Derived from (source file, position), which is unique by construction — belt and
        # braces against a chunk_id format that collides. Deterministic, so re-indexing
        # updates a point rather than duplicating it.
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chunk.source_file}#{chunk.chunk_index}")),
        vector={"dense": dense, "sparse": sparse},
        payload={
            "chunk_id": chunk.chunk_id,
            # Raw text, deliberately without the contextual prefix — this is what citations
            # display, and an excerpt must show the filing's words, not our synthesized header.
            "text": chunk.text,
            "company": chunk.company,
            "ticker": chunk.ticker,
            "cik": chunk.cik,
            "form_type": chunk.form_type,
            "fiscal_year": chunk.fiscal_year,
            "period_end": chunk.period_end,
            "filing_date": chunk.filing_date,
            "item_section": chunk.item_section,
            "chunk_index": chunk.chunk_index,
            "source_file": chunk.source_file,
            "token_count": chunk.token_count,
        },
    )


def index_chunks(chunks: list[Chunk]) -> int:
    """Embed and upsert. The prefix goes to the embedder; raw text goes to the payload."""
    if not chunks:
        return 0
    ensure_collection()
    qdrant = client()

    total = 0
    for start in range(0, len(chunks), UPSERT_BATCH):
        batch = chunks[start : start + UPSERT_BATCH]
        texts = [embedding_text(c) for c in batch]
        dense = dense_vectors(texts)
        sparse = sparse_vectors(texts)
        qdrant.upsert(
            collection_name=settings().collection,
            points=[_point(c, d, s) for c, d, s in zip(batch, dense, sparse, strict=True)],
        )
        total += len(batch)
    return total


def count(source_files: list[str] | None = None) -> int:
    """Points in the collection, or just those from the named filings.

    The filtered form exists so a subset re-index can be reconciled against its own scope
    rather than against the whole collection — see `main`.
    """
    if not qdrant_reachable() or not client().collection_exists(settings().collection):
        return 0
    query_filter = (
        models.Filter(
            must=[
                models.FieldCondition(
                    key="source_file", match=models.MatchAny(any=source_files)
                )
            ]
        )
        if source_files
        else None
    )
    return client().count(
        settings().collection, count_filter=query_filter, exact=True
    ).count


def ensure_indexed(source_file: str = SEED_FILING) -> int:
    """Index the filing if the collection is empty. Idempotent, so tests can call it freely."""
    existing = count()
    if existing:
        return existing
    return index_chunks(chunk_filing(source_file))


def main(argv: list[str]) -> int:
    from src.config import settings as _settings

    if not qdrant_reachable():
        print(
            f"Qdrant unreachable at {_settings().qdrant_url}. Try: docker compose up -d",
            flush=True,
        )
        return 1

    if "--all" in argv:
        files = sorted(p.name for p in _settings().corpus_dir.glob("*.txt"))
    elif named := [arg for arg in argv if not arg.startswith("-")]:
        # A named subset, because a metadata fix rarely touches every filing. Ticket 15
        # changed the derived period for exactly the 54 filings with no `Report Period`
        # header, and re-embedding the other 192 would have cost four times as much for no
        # change — point ids are deterministic (source file + position), so re-indexing a
        # subset updates those points and leaves the rest untouched.
        missing = [n for n in named if not (_settings().corpus_dir / n).is_file()]
        if missing:
            print(f"not in {_settings().corpus_dir}: {missing}", flush=True)
            return 1
        files = named
    else:
        files = [SEED_FILING]

    ensure_collection(recreate="--recreate" in argv)
    total = 0
    for position, name in enumerate(files, 1):
        indexed = index_chunks(chunk_filing(name))
        total += indexed
        # flush: Python buffers stdout when it is not a tty, so a 15-minute run over the
        # full corpus otherwise shows nothing at all until it finishes.
        print(
            f"[{position}/{len(files)}] {name}: {indexed} chunks (total {total})",
            flush=True,
        )
    # Reconcile what we sent against what landed. Point ids are deterministic, so a
    # collision overwrites silently — this run once reported 29,499 chunks while the
    # collection held 21,453, and nothing raised. A count that disagrees is the cheapest
    # possible detector, so it is checked rather than trusted.
    stored = count()
    print(
        f"done — sent {total} chunks, collection '{_settings().collection}' holds {stored} "
        f"at {_settings().qdrant_url}",
        flush=True,
    )

    # Reconcile against the right denominator. Comparing `total` to the whole collection is
    # only meaningful when the whole collection was just written; on a named subset it
    # reports nonsense (re-indexing 54 filings once claimed "-19573 chunks did not land").
    # For a subset, count only the points belonging to the files that were sent.
    if "--all" in argv:
        expected_scope = stored
    else:
        expected_scope = count(source_files=files)

    if expected_scope != total:
        print(
            f"WARNING: sent {total} chunks but the index holds {expected_scope} for those "
            f"files. Deterministic point ids mean duplicates overwrite; check chunk_id "
            f"uniqueness.",
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
