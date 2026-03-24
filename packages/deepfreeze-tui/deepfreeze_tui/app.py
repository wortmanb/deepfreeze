"""Main Textual app for deepfreeze TUI - lazygit style."""

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Static, OptionList

from .dialogs import ConfirmDialog, ThawDialog
from .modals import HelpPanel
from .widgets.panels import (
    ActivityPanel,
    BucketPanel,
    ConfigPanel,
    DetailPanel,
    ILMPanel,
    RepoPanel,
    ThawPanel,
)


class DeepfreezeApp(App):
    """Lazygit-style TUI for deepfreeze."""

    CSS_PATH = "styles/theme.tcss"
    TITLE = "deepfreeze"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "show_help", "Help", key_display="?"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("1", "focus_panel('repos')", "Repos", show=False),
        Binding("2", "focus_panel('thaw-requests')", "Thaw", show=False),
        Binding("3", "focus_panel('ilm-policies')", "ILM", show=False),
        Binding("4", "focus_panel('buckets')", "Buckets", show=False),
        Binding("5", "focus_panel('config-panel')", "Config", show=False),
        Binding("6", "focus_panel('detail-panel')", "Detail", show=False),
    ]

    def __init__(self, config_path=None, refresh_interval=30, local=False, server_url=None):
        super().__init__()
        self.config_path = config_path
        self.refresh_interval = refresh_interval
        self._local = local
        self._server_url = server_url
        self._client = None  # TuiClient or DeepfreezeService
        self._is_remote = False
        self._status_data: dict = {}
        self._sse_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        """Compose the lazygit-style layout."""
        yield Static(
            "[bold]deepfreeze[/bold]  [dim]connecting...[/dim]",
            id="status-bar",
        )

        with Horizontal(id="main"):
            with Vertical(id="left-col"):
                yield RepoPanel()
                yield ThawPanel()
                yield ILMPanel()
                yield BucketPanel()
                yield ConfigPanel()

            with Vertical(id="right-col"):
                yield DetailPanel()
                yield ActivityPanel()

        yield Footer()

        yield HelpPanel()
        yield ThawDialog()
        yield ConfirmDialog()

    def on_mount(self) -> None:
        """Initialize client and start data loading."""
        self._init_client()
        self.query_one("#repos").focus()
        self.run_worker(self._load_data())

        if self._is_remote:
            # SSE replaces polling in remote mode
            self._sse_task = asyncio.create_task(self._sse_listener())
            # Still do a slower poll as fallback (SSE might miss reconnects)
            if self.refresh_interval > 0:
                self.set_interval(max(self.refresh_interval, 60), self._load_data)
        else:
            # Local mode: poll like before
            if self.refresh_interval > 0:
                self.set_interval(self.refresh_interval, self._load_data)

    def _init_client(self) -> None:
        """Initialize remote or local client based on config."""
        server_url = self._server_url

        if not self._local and not server_url:
            # Check config for server URL
            try:
                import yaml
                if self.config_path:
                    with open(self.config_path) as f:
                        config = yaml.safe_load(f) or {}
                    server_cfg = config.get("server", {})
                    server_url = server_cfg.get("url")
            except Exception:
                pass

        if not self._local and server_url:
            # Remote mode
            from .client import TuiClient
            import os

            api_token = os.environ.get("DEEPFREEZE_SERVER_API_TOKEN")
            if not api_token:
                try:
                    import yaml
                    if self.config_path:
                        with open(self.config_path) as f:
                            config = yaml.safe_load(f) or {}
                        api_token = config.get("server", {}).get("api_token")
                except Exception:
                    pass

            self._client = TuiClient(server_url=server_url, api_token=api_token)
            self._is_remote = True
        else:
            # Local mode — use DeepfreezeService directly
            try:
                from deepfreeze_service import DeepfreezeService, PollingConfig
                self._client = DeepfreezeService(
                    config_path=self.config_path,
                    polling_config=PollingConfig(
                        enabled=True,
                        interval_seconds=self.refresh_interval,
                    ),
                )
            except Exception as e:
                self._update_status_bar(error=str(e))

    async def _load_data(self) -> None:
        """Fetch status data and populate all panels."""
        if not self._client:
            return

        try:
            if self._is_remote:
                status_data = await self._client.get_status(force_refresh=True)
            else:
                status = await self._client.get_status(force_refresh=True)
                status_data = status.model_dump()

            self._status_data = status_data
            self._populate_panels(status_data)

            # Load audit history
            try:
                if self._is_remote:
                    history = await self._client.get_action_history(limit=50)
                else:
                    history = self._client.get_action_history(limit=50)
                    history = [h.model_dump() for h in history]
                self.query_one(ActivityPanel).update_history(history)
            except Exception:
                pass

        except Exception as e:
            self._update_status_bar(error=str(e))

    def _populate_panels(self, data: dict) -> None:
        """Update all panels from status data dict."""
        repos = data.get("repositories", [])
        thaw_reqs = data.get("thaw_requests", [])
        buckets = data.get("buckets", [])
        ilm = data.get("ilm_policies", [])
        settings = data.get("settings")

        self.query_one(RepoPanel).update_repos(repos)
        self.query_one(ThawPanel).update_requests(thaw_reqs)
        self.query_one(BucketPanel).update_buckets(buckets)
        self.query_one(ILMPanel).update_policies(ilm)
        self.query_one(ConfigPanel).update_config(settings)
        self.query_one(DetailPanel).update_all_repos(repos)

        # Update status bar
        cluster = data.get("cluster", {})
        cluster_name = cluster.get("name", "?") if isinstance(cluster, dict) else "?"
        health = cluster.get("status", "?") if isinstance(cluster, dict) else "?"
        health_color = {"green": "green", "yellow": "yellow", "red": "red"}.get(health, "dim")
        errors = data.get("errors", [])

        mode = "[dim]remote[/dim]" if self._is_remote else "[dim]local[/dim]"
        status_text = (
            f"[bold]deepfreeze[/bold] {mode}  "
            f"cluster:[{health_color}]{cluster_name}[/{health_color}]  "
            f"repos:{len(repos)}  thaw:{len(thaw_reqs)}  "
            f"buckets:{len(buckets)}  ilm:{len(ilm)}"
        )
        if errors:
            status_text += f"  [red]errors:{len(errors)}[/red]"

        self._update_status_bar(text=status_text)

        # Default to All Repos view
        detail = self.query_one(DetailPanel)
        detail.set_context("repos")
        detail.show_all_repos_tab()

    async def _sse_listener(self) -> None:
        """Listen for SSE events and trigger UI updates."""
        if not self._is_remote:
            return
        try:
            async for event in self._client.subscribe_events():
                event_type = event.get("event", "")
                if event_type in ("status.changed", "job.completed", "job.failed"):
                    # Refresh all panels
                    await self._load_data()
                elif event_type == "job.started":
                    data = event.get("data", {})
                    self.notify(
                        f"Job started: {data.get('type', '?')}",
                        severity="information",
                        timeout=3,
                    )
        except asyncio.CancelledError:
            pass

    def _update_status_bar(self, text: str = None, error: str = None) -> None:
        bar = self.query_one("#status-bar", Static)
        if error:
            safe = error.replace("[", "\\[").replace("]", "\\]")
            bar.update(f"[bold]deepfreeze[/bold]  [red]{safe}[/red]")
        elif text:
            bar.update(text)

    # -- Selection handlers --

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        source_id = event.option_list.id
        detail = self.query_one(DetailPanel)

        if detail._populating:
            return

        if source_id == "repos":
            detail.set_context("repos")
            repo = self.query_one(RepoPanel).get_selected_repo()
            if repo:
                detail.show_repo_detail(repo)
        elif source_id == "thaw-requests":
            detail.set_context("thaw")
            req = self.query_one(ThawPanel).get_selected_request()
            if req:
                detail.show_thaw_detail(req)
                if req.get("status") == "in_progress":
                    self.run_worker(self._load_restore_progress(req))
        elif source_id == "buckets":
            detail.set_context("buckets")
            bucket = self.query_one(BucketPanel).get_selected_bucket()
            if bucket:
                detail.show_bucket_detail(bucket)
        elif source_id == "ilm-policies":
            detail.set_context("ilm")
            policy = self.query_one(ILMPanel).get_selected_policy()
            if policy:
                detail.show_ilm_detail(policy)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        source_id = event.option_list.id
        if source_id == "repos":
            detail = self.query_one(DetailPanel)
            repo = self.query_one(RepoPanel).get_selected_repo()
            if repo:
                detail.show_repo_detail(repo)

    # -- Actions --

    def action_focus_panel(self, panel_id: str) -> None:
        try:
            self.query_one(f"#{panel_id}").focus()
        except Exception:
            pass

    def action_refresh(self) -> None:
        self.run_worker(self._load_data())
        self.notify("Refreshing...", timeout=2)

    def action_show_help(self) -> None:
        focused = self.focused
        focused_id = ""
        if focused is not None:
            focused_id = focused.id or ""
        self.query_one(HelpPanel).toggle(focused_panel_id=focused_id)

    # -- Action implementations --

    def action_do_rotate(self) -> None:
        if not self._client:
            self.notify("Not connected", severity="error")
            return
        self.query_one(ConfirmDialog).show(
            message="Rotate will create a new repository and archive old ones.\nProceed?",
            title="Confirm Rotate",
            callback=self._on_rotate_confirmed,
        )

    def _on_rotate_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self.query_one(ActivityPanel).log_command("rotate")
        self.run_worker(self._exec_rotate())

    async def _exec_rotate(self) -> None:
        if self._is_remote:
            result = await self._client.rotate()
        else:
            result = (await self._client.rotate()).model_dump()
        self._show_result("Rotate", result)

    def action_do_thaw(self) -> None:
        if not self._client:
            self.notify("Not connected", severity="error")
            return
        self.query_one(ThawDialog).show(callback=self._handle_thaw_input)

    def _handle_thaw_input(self, params: dict) -> None:
        if not self._client:
            return
        self.query_one(ActivityPanel).log_command(
            "thaw", f"{params['start_date']} to {params['end_date']}"
        )
        self.run_worker(self._exec_thaw(params))

    async def _exec_thaw(self, params: dict) -> None:
        if self._is_remote:
            result = await self._client.thaw_create(
                start_date=params["start_date"],
                end_date=params["end_date"],
                duration=params.get("duration", 7),
            )
        else:
            from datetime import datetime
            start = datetime.fromisoformat(params["start_date"])
            end = datetime.fromisoformat(params["end_date"])
            duration = params.get("duration", 7)
            result = (await self._client.thaw_create(
                start_date=start, end_date=end, duration=duration,
            )).model_dump()
        self._show_result("Thaw", result)

    def action_do_cleanup(self) -> None:
        if not self._client:
            self.notify("Not connected", severity="error")
            return
        self.query_one(ConfirmDialog).show(
            message="Cleanup will unmount expired repos and delete old thaw requests.\nProceed?",
            title="Confirm Cleanup",
            callback=self._on_cleanup_confirmed,
        )

    def _on_cleanup_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        self.query_one(ActivityPanel).log_command("cleanup")
        self.run_worker(self._exec_cleanup())

    async def _exec_cleanup(self) -> None:
        if self._is_remote:
            result = await self._client.cleanup()
        else:
            result = (await self._client.cleanup()).model_dump()
        self._show_result("Cleanup", result)

    def action_do_repair(self) -> None:
        if not self._client:
            self.notify("Not connected", severity="error")
            return
        self.query_one(ActivityPanel).log_command("repair-metadata")
        self.run_worker(self._exec_repair())

    async def _exec_repair(self) -> None:
        if self._is_remote:
            result = await self._client.repair_metadata()
        else:
            result = (await self._client.repair_metadata()).model_dump()
        self._show_result("Repair", result)

    def action_do_refreeze(self) -> None:
        if not self._client:
            self.notify("Not connected", severity="error")
            return
        req = self.query_one(ThawPanel).get_selected_request()
        if not req:
            self.notify("No thaw request selected", severity="warning")
            return
        req_id = req.get("id", req.get("request_id"))
        if not req_id:
            self.notify("Could not determine request ID", severity="error")
            return
        short_id = req_id[-8:] if len(req_id) > 8 else req_id
        self._pending_refreeze_id = req_id
        self.query_one(ConfirmDialog).show(
            message=f"Refreeze will unmount indices and refreeze request {short_id}.\nProceed?",
            title="Confirm Refreeze",
            callback=self._on_refreeze_confirmed,
        )

    def _on_refreeze_confirmed(self, confirmed: bool) -> None:
        if not confirmed:
            return
        req_id = getattr(self, "_pending_refreeze_id", None)
        if not req_id:
            return
        short_id = req_id[-8:] if len(req_id) > 8 else req_id
        self.query_one(ActivityPanel).log_command("refreeze", short_id)
        self.run_worker(self._exec_refreeze(req_id))

    async def _exec_refreeze(self, request_id: str) -> None:
        if self._is_remote:
            result = await self._client.refreeze(request_id=request_id)
        else:
            result = (await self._client.refreeze(request_id=request_id)).model_dump()
        self._show_result("Refreeze", result)

    def _show_result(self, action_name: str, result: dict) -> None:
        """Display action result in the detail panel and as notification."""
        detail = self.query_one(DetailPanel)
        content = detail.query_one("#detail-content", Static)

        success = result.get("success", False)
        if success:
            severity = "information"
            lines = [
                f"[bold green]{action_name} completed successfully[/bold green]",
                "",
                f"  Duration: {result.get('duration_ms', 0)}ms",
                f"  Summary:  {result.get('summary', '')}",
            ]
            details = result.get("details", [])
            if details:
                lines.extend(["", "  Details:"])
                for d in details:
                    target = d.get("target", "?") if isinstance(d, dict) else "?"
                    status = d.get("status", "") if isinstance(d, dict) else ""
                    lines.append(f"    - {target}: {status}")
        else:
            severity = "error"
            lines = [
                f"[bold red]{action_name} failed[/bold red]",
                "",
                f"  Summary: {result.get('summary', '')}",
            ]
            errors = result.get("errors", [])
            if errors:
                lines.extend(["", "  Errors:"])
                for e in errors:
                    msg = e.get("message", str(e)) if isinstance(e, dict) else str(e)
                    lines.append(f"    [red]- {msg}[/red]")

        content.update("\n".join(lines))

        self.query_one(ActivityPanel).log_result(
            action_name.lower(),
            success,
            result.get("summary", ""),
            result.get("duration_ms", 0),
        )

        safe_summary = result.get("summary", "").replace("[", "\\[").replace("]", "\\]")
        self.notify(f"{action_name}: {safe_summary}", severity=severity, timeout=5)

        self.run_worker(self._load_data())

    async def _load_restore_progress(self, req: dict) -> None:
        req_id = req.get("request_id") or req.get("id")
        if not req_id or not self._client:
            return

        try:
            detail = self.query_one(DetailPanel)
            detail.append_restore_progress([{
                "repo": "...", "total": 0, "restored": 0,
                "in_progress": 0, "not_restored": 0, "complete": False,
                "error": "loading...",
            }])

            if self._is_remote:
                progress = await self._client.get_thaw_restore_progress(str(req_id))
            else:
                progress = await self._client.get_thaw_restore_progress(str(req_id))

            detail.show_thaw_detail(req)
            detail.append_restore_progress(progress)
        except Exception as e:
            detail = self.query_one(DetailPanel)
            detail.append_restore_progress([{
                "repo": "error", "total": 0, "restored": 0,
                "in_progress": 0, "not_restored": 0, "complete": False,
                "error": str(e),
            }])
