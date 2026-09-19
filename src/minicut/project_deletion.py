"""Prevent project removal while requests are writing local project data."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class ProjectDeletionGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.writers = 0
        self.deleting = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        mutation = scope["type"] == "http" and scope["method"] in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }
        if not mutation:
            await self.app(scope, receive, send)
            return
        deletion = scope["method"] == "DELETE"
        # No await between checking and registering: atomic on the ASGI event loop.
        # Include response background tasks, while still allowing cancellation calls.
        if self.deleting or (deletion and self.writers):
            await JSONResponse(
                {"detail": "有任务或文件操作正在进行，请稍后再试"}, status_code=409
            )(scope, receive, send)
            return
        self.writers += 1
        self.deleting = deletion
        try:
            await self.app(scope, receive, send)
        finally:
            self.writers -= 1
            if deletion:
                self.deleting = False
