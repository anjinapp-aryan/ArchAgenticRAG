"""PEP corpus ingestion: reStructuredText -> docutils -> HTML -> Docling -> HybridChunker.

Docling has no reStructuredText backend, so docutils' own PEP reader (the reference RST
implementation, which also parses the RFC 2822 PEP header) renders each PEP to HTML. Docling
converts that HTML into a DoclingDocument, and its HybridChunker produces token-bounded,
heading-aware chunks.

The only transforms we apply are to the docutils tree before rendering:
  * drop the auto-generated table of contents (navigation, not content);
  * unwrap hyperlinks to plain text, so Docling does not split sentences around links;
  * turn the PEP header field list into "Field: value" paragraphs. Docling skips the header
    when it comes as an HTML definition list, and its chunker drops it when it comes as a
    table, so Title, Status, Python-Version etc. would otherwise never be retrievable.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from archagenticrag.rag.settings import ChunkingSettings

_DOCUTILS_SETTINGS = {
    "report_level": 5,  # Sphinx-only roles/directives in newer PEPs are kept as text, not reported
    "halt_level": 5,
    "embed_stylesheet": False,
    "output_encoding": "utf-8",
}


class CorpusError(RuntimeError):
    pass


@dataclass
class ParsedPep:
    doc_id: str
    source: str
    header: dict[str, str]
    html: bytes

    @property
    def title_line(self) -> str:
        return _title_line(self.header, self.doc_id)


def _title_line(header: dict[str, str], doc_id: str) -> str:
    return f"PEP {header.get('PEP', '?')} - {header.get('Title', doc_id)}"


@dataclass
class IngestReport:
    documents: int = 0
    chunks: int = 0
    chunks_per_document: dict[str, int] = field(default_factory=dict)


def load_corpus_manifest(corpus_dir: Path) -> dict[str, Any]:
    """Read MANIFEST.json and verify every file still matches its recorded sha256."""
    manifest = json.loads((corpus_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    for doc in manifest["documents"]:
        path = corpus_dir / doc["file"]
        if not path.exists():
            raise CorpusError(f"corpus file missing: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
            raise CorpusError(f"corpus file changed since MANIFEST.json was written: {path}")
    return manifest


def parse_pep(path: Path, doc_id: str, source: str) -> ParsedPep:
    from docutils import nodes
    from docutils.core import publish_doctree, publish_from_doctree

    tree = publish_doctree(
        path.read_text(encoding="utf-8"), source_path=str(path), reader="pep", settings_overrides=_DOCUTILS_SETTINGS
    )
    for topic in list(tree.findall(nodes.topic)):
        if "contents" in topic["classes"]:
            topic.parent.remove(topic)
    for ref in list(tree.findall(nodes.reference)):
        ref.replace_self(nodes.Text(ref.astext()))

    header: dict[str, str] = {}
    for field_list in list(tree.findall(nodes.field_list)):
        if "rfc2822" not in field_list["classes"]:
            continue
        paragraphs = []
        for fld in field_list.findall(nodes.field):
            name = fld.children[0].astext().strip()
            value = " ".join(fld.children[1].astext().split())
            header[name] = value
            paragraphs.append(nodes.paragraph(text=f"{name}: {value}"))
        field_list.replace_self(paragraphs)

    # Docling's HTML backend treats everything before the first heading as page furniture,
    # which its chunkers skip. Giving the document its real title as <h1> (as peps.python.org
    # does) keeps the header in the body.
    tree.insert(0, nodes.title(text=_title_line(header, doc_id)))

    html = publish_from_doctree(tree, writer="html4css1", settings_overrides=_DOCUTILS_SETTINGS)
    return ParsedPep(doc_id=doc_id, source=source, header=header, html=html)


class PepChunker:
    """Docling conversion + HybridChunker, configured from ChunkingSettings."""

    def __init__(self, settings: ChunkingSettings):
        from docling.chunking import HybridChunker
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter
        from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
        from transformers import AutoTokenizer

        self._converter = DocumentConverter(allowed_formats=[InputFormat.HTML])
        self.tokenizer = HuggingFaceTokenizer(
            tokenizer=AutoTokenizer.from_pretrained(settings.tokenizer), max_tokens=settings.max_tokens
        )
        self._chunker = HybridChunker(tokenizer=self.tokenizer, merge_peers=settings.merge_peers)

    def chunk(self, pep: ParsedPep) -> list[Document]:
        from docling.datamodel.base_models import DocumentStream

        result = self._converter.convert(DocumentStream(name=f"{pep.doc_id}.html", stream=io.BytesIO(pep.html)))
        if result.status.name != "SUCCESS":
            raise CorpusError(f"Docling could not convert {pep.source}: {result.status.name}")
        docs = []
        for index, chunk in enumerate(self._chunker.chunk(dl_doc=result.document)):
            headings = list(chunk.meta.headings or [])
            # The PEP title line gives every chunk its document context (Docling's own
            # contextualize() adds the section headings, and already includes the title
            # for chunks that sit directly under it).
            body = self._chunker.contextualize(chunk)
            text = body if body.startswith(pep.title_line) else f"{pep.title_line}\n{body}"
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "doc_id": pep.doc_id,
                        "source": pep.source,
                        "title": pep.header.get("Title", ""),
                        "pep": pep.header.get("PEP", ""),
                        "status": pep.header.get("Status", ""),
                        "section": " > ".join(headings),
                        "chunk_id": f"{pep.doc_id}#{index:03d}",
                        "chunk_index": index,
                    },
                )
            )
        return docs


def chunk_corpus(corpus_dir: Path, settings: ChunkingSettings) -> tuple[list[Document], dict[str, Any], IngestReport]:
    """Parse and chunk every document listed in the corpus manifest (after verifying hashes)."""
    logging.getLogger("docling").setLevel(logging.WARNING)
    manifest = load_corpus_manifest(corpus_dir)
    chunker = PepChunker(settings)
    report = IngestReport()
    all_docs: list[Document] = []
    for entry in manifest["documents"]:
        source = f"{corpus_dir.as_posix()}/{entry['file']}"
        docs = chunker.chunk(parse_pep(corpus_dir / entry["file"], entry["doc_id"], source))
        report.documents += 1
        report.chunks += len(docs)
        report.chunks_per_document[entry["doc_id"]] = len(docs)
        all_docs.extend(docs)
    return all_docs, manifest, report
