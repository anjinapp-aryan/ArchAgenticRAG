---
name: license-audit
description: "Use before adding or recommending any dependency, model, dataset or copied pattern in ArchAgenticRAG, and when a licence is questioned. Verifies package, repository and model licences from primary sources, classifies each as Known, Unknown or Needs legal review, and rejects anything unclear."
---

# license-audit

## Purpose
Never depend on something whose terms are not verified. The register of accepted components is `THIRD_PARTY_NOTICES.md`.

## When to use
Whenever `reuse-audit` shortlists a component, before a model download, and before adopting an adapted pattern.

## Inputs
Package, repository, model or dataset identifiers; intended use (this project is a learning and portfolio project, but keep commercial use possible).

## Workflow
1. **Package.** `.venv/Scripts/python -c "import importlib.metadata as m; d=m.metadata('<pkg>'); print(d.get('License-Expression') or d.get('License'), [c for c in d.get_all('Classifier') or [] if 'License' in c])"` if installed, else `curl -s https://pypi.org/pypi/<pkg>/json` and read `license_expression`, `license` and classifiers.
2. **Repository.** Open the LICENSE file of the official repository and compare with the package claim. A README line alone is not enough.
3. **Model.** `curl -s https://huggingface.co/api/models/<id>` and read `cardData.license`; then read the model card. Community conversions (ONNX, quantised ports) can lack a licence even when the base model has one: the repository you actually download from must state it.
4. **Dependencies.** `uv pip install --python .venv/Scripts/python.exe --dry-run <pkg>` lists what would be added; check any new package that is not obviously permissive.
5. **Classify** each item: **Known** (verified permissive, for example MIT, Apache-2.0, BSD), **Unknown** (not stated or not found), **Needs legal review** (copyleft such as GPL/AGPL, non-commercial such as CC-BY-NC, custom or conflicting terms).
6. **Record** accepted items in `THIRD_PARTY_NOTICES.md` (name, version, licence, use). Adapted patterns also need the source commit and the notice text.

## Required checks
- Package licence and model licence are checked separately.
- Evidence is a command or URL from this session.
- Unknown and Needs legal review items are listed, not silently dropped.

## Output
A table `Component | Licence | Source checked | Class | Decision`. Rule: Unknown means reject for implementation. This is an engineering check, not legal advice.

## STOP
- A licence is unclear, non-commercial or copyleft and the component is still wanted: stop and ask.
- Code from a repository without a permissive licence would be copied.
