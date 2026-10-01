from __future__ import annotations

import shutil

import pytest

from archagenticrag.rag.ingestion import CorpusError, load_corpus_manifest, parse_pep

from .conftest import CORPUS_DIR


def test_corpus_manifest_hashes_verify():
    manifest = load_corpus_manifest(CORPUS_DIR)
    assert len(manifest["documents"]) == 13


def test_tampered_corpus_is_rejected(tmp_path):
    corpus = tmp_path / "peps"
    shutil.copytree(CORPUS_DIR, corpus)
    (corpus / "pep-0020.rst").write_text("changed", encoding="utf-8")
    with pytest.raises(CorpusError, match="changed"):
        load_corpus_manifest(corpus)


def test_parse_pep_extracts_header_and_keeps_it_as_body_text():
    pep = parse_pep(CORPUS_DIR / "pep-0563.rst", "pep-0563", "data/corpus/peps/pep-0563.rst")
    assert pep.header["Status"] == "Superseded"
    assert pep.header["Superseded-By"] == "649, 749"
    assert pep.title_line == "PEP 563 - Postponed Evaluation of Annotations"
    html = pep.html.decode("utf-8")
    assert "<h1" in html and "Postponed Evaluation of Annotations" in html
    assert "<p>Status: Superseded</p>" in html
    assert 'class="contents' not in html  # auto table of contents removed
    assert "reference external" not in html  # hyperlinks in text unwrapped to plain text


@pytest.mark.parametrize("path", sorted(CORPUS_DIR.glob("*.rst")), ids=lambda p: p.stem)
def test_every_corpus_pep_parses(path):
    pep = parse_pep(path, path.stem, str(path))
    assert pep.header.get("Title")
    assert pep.header.get("Status")
