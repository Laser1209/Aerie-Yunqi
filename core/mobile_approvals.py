"""Owner-only approval adapter for the isolated mobile gateway.

This module wraps the shared desktop ComputerController approval pipeline so
the mobile gateway can list pending approvals and render decisions.  Every
endpoint is owner-only; guests are rejected before touching the controller.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.mobile_identity import MobilePrincipal

logger = logging.getLogger(__name__)


class MobileApprovalError(Exception):
    """Raised when an approval operation cannot be completed."""

    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _controller() -> Any:
    from core.companion import get_companion
    from core.computer_control import ComputerController

    comp = get_companion()
    if comp is not None and hasattr(comp, "computer_controller") and comp.computer_controller:
        return comp.computer_controller
    return ComputerController()


def list_pending_approvals(principal: MobilePrincipal) -> dict[str, Any]:
    """Return pending approvals visible to the owner (redacted)."""
    _require_owner(principal)
    try:
        approvals = _controller().get_pending_approvals()
    except Exception:
        logger.warning("readonly approval list failed", exc_info=True)
        raise MobileApprovalError("approvals_unavailable", status_code=503) from None
    items = []
    for entry in approvals or []:
        items.append(
            {
                "approvalId": str(entry.get("id") or ""),
                "action": str(entry.get("action") or ""),
                "riskLevel": str(entry.get("risk_level") or ""),
                "description": str(entry.get("description") or ""),
                "params": entry.get("params") or {},
                "createdAt": entry.get("created_at", time.time()),
            }
        )
    return {"items": items, "count": len(items)}


def get_approval(principal: MobilePrincipal, approval_id: str) -> dict[str, Any]:
    """Return a single pending approval detail (owner-only)."""
    _require_owner(principal)
    items = list_pending_approvals(principal)["items"]
    for item in items:
        if item["approvalId"] == approval_id:
            return item
    raise MobileApprovalError("approval_not_found", status_code=404)


def decide_approval(
    principal: MobilePrincipal,
    approval_id: str,
    *,
    approved: bool,
    whitelist: bool = False,
    blacklist: bool = False,
) -> dict[str, Any]:
    """Approve or reject a pending approval (owner-only)."""
    _require_owner(principal)
    ctrl = _controller()
    if approved:
        result = ctrl.approve_action(approval_id, whitelist=whitelist)
        if not result:
            raise MobileApprovalError("approval_not_found", status_code=404)
        return {"approvalId": approval_id, "status": "approved", "whitelist": whitelist}
    result = ctrl.reject_action(approval_id, blacklist=blacklist)
    if not result:
        raise MobileApprovalError("approval_not_found", status_code=404)
    return {"approvalId": approval_id, "status": "rejected", "blacklist": blacklist}


def _require_owner(principal: MobilePrincipal) -> None:
    if principal.role != "owner":
        raise MobileApprovalError("forbidden", status_code=403)
