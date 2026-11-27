from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app_core import services
from app_core.support import DEFAULT_REPO, collect_support_diagnostics, record_support_report, upload_support_report, list_support_reports, delete_support_report, clear_support_reports, cleanup_support_reports
from ui.web import deps
from ui.web.rendering import render
from ui.web.route_utils import flash_redirect

router = APIRouter()


@router.get("/support/report")
def support_report(request: Request):
    """In-app issue reporting: sanitized diagnostics + user-authored report builder."""
    # Client context is best provided by browser/JS; include safe server-known hints.
    qp = request.query_params
    context = {
        "path": str(qp.get("path") or request.url.path),
        "source": "web",
    }
    prefill = {"title": "", "actual": "", "notes": ""}
    # If coming from an in-app error page, include sanitized last error context for prefill.
    if str(qp.get("from_error") or "") in ("1", "true", "yes"):
        try:
            sess = deps.get_session(request)
            last = sess.get("last_error_report") or {}
            ref = str(qp.get("ref") or "")
            if isinstance(last, dict) and (not ref or str(last.get("ref") or "") == ref):
                em = last.get("error_message") or ""
                et = last.get("error_type") or "Error"
                ep = last.get("path") or ""
                er = last.get("ref") or ""
                prefill["title"] = f"App error: {et}"[:120]
                prefill["actual"] = (
                    f"Unexpected error in the web app.\nRef: {er}\nPath: {ep}\nError: {et}: {em}".strip()
                )
                prefill["notes"] = "Reported from in-app error page. Please add steps to reproduce."
                context.update(
                    {
                        "error_code": er,
                        "error_message": f"{et}: {em}" if em else et,
                        "path": ep or context.get("path"),
                    }
                )
        except Exception:
            pass

    diagnostics = collect_support_diagnostics(context=context, include_update_check=False)
    # Safe JSON for embedding in <script type="application/json">
    diagnostics_json = json.dumps(diagnostics, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    data_contribution_enabled = (str(services.get_setting("app_data_contribution_enabled", "false")).lower() == "true" or str(services.get_setting("assistant_training_share_enabled", "false")).lower() == "true")
    try:
        retention_days = int(services.get_setting("support_report_retention_days", "90") or "90")
    except Exception:
        retention_days = 90
    try:
        cleanup_support_reports(retention_days)
    except Exception:
        pass
    try:
        recorded_reports = list_support_reports(limit=20)
    except Exception:
        recorded_reports = []
    return render(
        request,
        "support/report.html",
        {
            "title": "Report issue",
            "diagnostics": diagnostics,
            "diagnostics_json": diagnostics_json,
            "github_repo": DEFAULT_REPO,
            "prefill": prefill,
            "data_contribution_enabled": data_contribution_enabled,
            "csrf_token": deps.csrf_token(request),
            "recorded_reports": recorded_reports,
            "support_report_retention_days": retention_days,
        },
    )


@router.post("/support/report/send")
async def support_report_send(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON body."}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Invalid report payload."}, status_code=400)
    report = body.get("report") if isinstance(body.get("report"), dict) else body
    share = bool(body.get("share") or body.get("contribute") or body.get("upload"))
    # global opt-in allows sending; per-request share is explicit consent for this report
    global_opt_in = (str(services.get_setting("app_data_contribution_enabled", "false")).lower() == "true" or str(services.get_setting("assistant_training_share_enabled", "false")).lower() == "true")
    if share and not global_opt_in:
        # allow explicit per-report share even if global setting off? safer to require explicit intent in request;
        # but honor "checked the data contribution..." - we require share flag from user action.
        pass

    result = {"ok": True, "recorded": False, "uploaded": False, "upload": None, "path": None}
    try:
        path = record_support_report(report)
        result["recorded"] = True
        result["path"] = path.name
    except Exception as e:
        result["recorded"] = False
        result["record_error"] = str(e)

    if share:
        upload_url = str(services.get_setting("support_report_upload_url", "") or "").strip() or None
        up = upload_support_report(report, upload_url=upload_url)
        result["uploaded"] = bool(up.get("ok"))
        result["upload"] = up
        result["ok"] = bool(result["recorded"] or result["uploaded"])
    return JSONResponse(result)


@router.post("/support/report/delete")
async def support_report_delete(request: Request):
    form = await deps.get_form(request)
    name = str(form.get("name") or "")
    ok = delete_support_report(name)
    return flash_redirect(request, "/support/report", "Support report deleted." if ok else "Report not found.", "success" if ok else "error")


@router.post("/support/report/clear")
async def support_report_clear(request: Request):
    await deps.get_form(request)
    n = clear_support_reports()
    return flash_redirect(request, "/support/report", f"Cleared {n} local support report(s).", "success")
