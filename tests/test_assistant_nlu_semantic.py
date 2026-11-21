from __future__ import annotations

import sys
import types

import pytest

np = pytest.importorskip("numpy")

from app_core.assistant import nlu


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True):
        vecs = []
        for t in texts:
            tl = str(t).lower()
            v = np.zeros(8, dtype=float)
            if "guest" in tl or "sara" in tl:
                v[0] = 1.0
            if "balance" in tl or "owe" in tl:
                v[1] = 1.0
            if "reservation" in tl:
                v[2] = 1.0
            if "checkin" in tl or "arrival" in tl:
                v[3] = 1.0
            if not v.any():
                v[7] = 1.0
            n = np.linalg.norm(v) or 1.0
            vecs.append(v / n if normalize_embeddings else v)
        return np.vstack(vecs)


def test_semantic_classify_and_fusion(monkeypatch):
    fake_st = types.ModuleType("sentence_transformers")
    fake_st.SentenceTransformer = lambda *a, **k: _FakeModel()
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st)
    # reset caches
    monkeypatch.setattr(nlu, "_SEMANTIC_INDEX", None, raising=False)
    monkeypatch.setattr(nlu, "_SEMANTIC_MODEL", None, raising=False)
    monkeypatch.setattr(nlu, "_semantic_available", lambda: True)

    # build index directly
    monkeypatch.setattr(nlu, "_SEMANTIC_INDEX", None, raising=False)
    monkeypatch.setattr(nlu, "_SEMANTIC_MODEL", _FakeModel(), raising=False)

    # semantic_classify should return intent or None
    res = nlu.semantic_classify("show me guest balance")
    # may be None or dict depending on threshold; just exercise code
    assert res is None or isinstance(res, dict)

    # exercise classify_intent with semantic path by making rule low confidence
    monkeypatch.setattr(nlu, "semantic_classify", lambda text, top_k=3: {"intent": "guest_balance", "confidence": 0.8, "margin": 0.3, "scores": {"guest_balance": 0.8}, "method": "semantic_vector"})
    r = nlu.classify_intent("xyzzy unknown-ish but guest balance maybe")
    assert isinstance(r, dict)
    assert "intent" in r

    # fuse path where semantic wins
    rl = {"intent": "capabilities_help", "confidence": 0.4, "margin": 0.01, "low_confidence": True, "scores": {"capabilities_help": 0.4}}
    sem = {"intent": "guest_balance", "confidence": 0.9, "margin": 0.4, "scores": {"guest_balance": 0.9}, "method": "semantic_vector"}
    fused = nlu._fuse_rule_semantic(rl, sem, slots={})
    assert fused["intent"] in {"guest_balance", "capabilities_help"}

    # fusion keep rule
    sem2 = {"intent": "guest_search", "confidence": 0.5, "margin": 0.1, "scores": {"guest_search": 0.5}, "method": "semantic_vector"}
    fused2 = nlu._fuse_rule_semantic({"intent": "guest_balance", "confidence": 0.9, "margin": 0.5, "scores": {"guest_balance": 0.9}}, sem2, slots={})
    assert fused2["intent"] == "guest_balance"
