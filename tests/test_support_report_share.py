from __future__ import annotations

import json
from pathlib import Path

from app_core import support


def test_record_list_delete_clear_cleanup_support_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "SUPPORT_REPORTS_DIR", tmp_path / "reports")
    p = support.record_support_report({"report_kind": "test", "msg": "hello"})
    assert p.exists()
    items = support.list_support_reports()
    assert len(items) == 1
    assert items[0]["name"].startswith("report-")
    assert support.delete_support_report(items[0]["name"]) is True
    assert support.list_support_reports() == []

    support.record_support_report({"a": 1})
    support.record_support_report({"b": 2})
    assert support.clear_support_reports() == 2
    assert support.list_support_reports() == []

    p1 = support.record_support_report({"c": 3})
    old = 1000
    os_utime = __import__("os").utime
    os_utime(p1, (old, old))
    assert support.cleanup_support_reports(retention_days=1) >= 1
    assert support.cleanup_support_reports(retention_days=0) == 0


def test_upload_support_report_success_and_errors(monkeypatch):
    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok":true,"id":1}'
    monkeypatch.setattr(support.urllib.request, "urlopen", lambda req, timeout=20: Resp())
    ok = support.upload_support_report({"x": 1}, upload_url="https://example.test/api/report")
    assert ok["ok"] is True

    bad = support.upload_support_report({"x": 1}, upload_url="ftp://bad")
    assert bad["ok"] is False

    def boom(*a, **k): raise RuntimeError("net")
    monkeypatch.setattr(support.urllib.request, "urlopen", boom)
    err = support.upload_support_report({"x": 1}, upload_url="https://example.test/api/report")
    assert err["ok"] is False

def test_support_report_edge_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "SUPPORT_REPORTS_DIR", tmp_path / "reports")
    # list on empty/nonexistent
    assert support.list_support_reports() == []
    # delete invalid names
    assert support.delete_support_report("../x.json") is False
    assert support.delete_support_report("not-report.json") is False
    assert support.delete_support_report("report-missing.json") is False
    # clear on nonexistent
    assert support.clear_support_reports() == 0
    # cleanup disabled
    support.record_support_report({"a": 1})
    assert support.cleanup_support_reports(retention_days=0) == 0
    # cleanup with invalid env
    monkeypatch.setenv("SPMS_SUPPORT_REPORT_RETENTION_DAYS", "bad")
    assert support.cleanup_support_reports(retention_days=None) >= 0
    # upload url default env
    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'not-json'
    monkeypatch.setattr(support.urllib.request, "urlopen", lambda req, timeout=20: Resp())
    r = support.upload_support_report({"x": 1}, upload_url="http://example.test/api/report")
    assert r["ok"] is False  # invalid json response
