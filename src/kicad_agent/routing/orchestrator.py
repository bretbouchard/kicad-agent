"""RoutingOrchestrator: batch routing dispatcher with audit trail and rollback.

Coordinates per-net dispatch to A* or Freerouting based on a RoutingStrategy,
logs every decision to a durable JSONL audit trail, and supports per-net
rollback via PcbIR-based surgical removal (H2 — no regex on S-expressions).

Threat model (T-100-02-01 through T-100-02-06):
- Strategy output is defensively validated (H4) before execution.
- PCB mutations are snapshotted via PersistentUndoStack before and after routing.
- Every dispatch decision is logged with fsync durability (H5).
- All writes are scoped to project_dir — no writes outside the project boundary.

Council corrections applied:
- C2: import_ses_into_pcb takes (ses_path: Path, pcb_content: str) and returns
  tuple[str, dict[str, int]] — NOT a net_filter parameter.
- H2: rollback_net uses PcbRawWriter.delete_segment/delete_via via UUID, NOT
  regex on raw S-expression text.
- CR-01: rollback_net joins on the UUID value carried by NativeSegment /
  NativeVia, NOT on extract_uuids parent_index. The parent_index diverges
  from NativeBoard.segments ordering on real boards (nested segments).
- CR-02: all writes go through atomic_write (temp + fsync + rename), NOT
  bare pcb_path.write_text.
- H4: _validate_strategy_result rejects unknown nets and invalid backends.
- M4: NOT thread-safe (documented in RoutingOrchestrator docstring).
- R3-L2: op_type tags are explicit constants ("route_board_pre", "route_board_post").
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kicad_agent.io.atomic_write import atomic_write
from kicad_agent.routing.audit import RoutingAuditEntry, RoutingAuditLog, now_iso
from kicad_agent.routing.strategy import (
    BoardState,
    DeterministicStrategy,
    Pin,
    RouterBackend,
    RoutingStrategy,
    RoutingStrategyResult,
)

logger = logging.getLogger(__name__)

# R3-L2: explicit op_type tag constants for PersistentUndoStack.push.
_OP_TYPE_ROUTE_PRE = "route_board_pre"
_OP_TYPE_ROUTE_POST = "route_board_post"


@dataclass(frozen=True)
class NetRouteResult:
    """Result of routing a single net within an orchestration run.

    Attributes:
        net_name: Name of the net that was routed.
        router_used: Which backend handled it.
        success: True if the backend produced a route.
        route_length_mm: Total route length in mm (0.0 if failed).
        via_count: Number of vias in the route.
        dispatch_reason: Why this router was chosen (for audit).
        notes: Free-text notes (e.g., fallback reason).
    """

    net_name: str
    router_used: RouterBackend
    success: bool
    route_length_mm: float
    via_count: int
    dispatch_reason: str
    notes: str = ""


@dataclass(frozen=True)
class RoutingOrchestrationResult:
    """Aggregate result of a full board route.

    Attributes:
        per_net: Dict mapping net name to its NetRouteResult.
        audit_path: Path to the JSONL audit trail file.
        total_routed: Count of nets successfully routed.
        total_failed: Count of nets that failed to route.
        total_rejected: Count of nets rejected by the human approval loop (0
            from route_board alone — rejections happen in the session).
        strategy_used: Name of the strategy class that produced assignments.
        elapsed_seconds: Wall-clock time from start to finish.
    """

    per_net: dict[str, NetRouteResult]
    audit_path: Path
    total_routed: int
    total_failed: int
    total_rejected: int
    strategy_used: str
    elapsed_seconds: float


class RoutingOrchestrator:
    """Batch routing dispatcher with audit trail and per-net rollback.

    Thread safety (M4): NOT thread-safe. The audit log file handle races
    under concurrent append. Create one RoutingOrchestrator instance per
    thread. If Phase 98 requires concurrency, add a threading.Lock to
    RoutingAuditLog.append.

    Validation (H4): route_board validates strategy output before dispatch.
    Every net in router_assignment must exist in netlist; every RouterBackend
    must be a valid enum value. Raises ValueError on violation.

    Rollback (H2): rollback_net surgically removes a single net's routed
    segments and vias via PcbRawWriter.delete_segment/delete_via (UUID-based).
    Footprint pad net declarations are preserved — only routed tracks are
    removed. This replaces the unsafe regex approach which corrupts pad
    definitions because (net "name") appears in both segment and pad contexts.
    """

    def __init__(self, strategy: RoutingStrategy | None = None) -> None:
        self._strategy = strategy if strategy is not None else DeterministicStrategy()

    # ------------------------------------------------------------------
    # H4: Strategy output validation
    # ------------------------------------------------------------------

    def _validate_strategy_result(
        self,
        strategy_result: RoutingStrategyResult,
        netlist: dict[str, list[Pin]],
    ) -> None:
        """H4: Defensive validation of strategy output.

        Raises ValueError if any net in router_assignment is unknown
        (not in netlist) or any backend is not a valid RouterBackend enum.

        This is the belt-and-suspenders validation layer. DeterministicStrategy
        is trusted (deterministic code), but Phase 98's AI advisor output will
        flow through here before execution.
        """
        known_nets = set(netlist.keys())
        for net, backend in strategy_result.router_assignment.items():
            if net not in known_nets:
                raise ValueError(
                    f"unknown net '{net}' in router_assignment (not in netlist)"
                )
            if not isinstance(backend, RouterBackend):
                raise ValueError(
                    f"invalid backend '{backend!r}' for net '{net}' "
                    f"(must be RouterBackend enum)"
                )

    # ------------------------------------------------------------------
    # R-7: Batch orchestration
    # ------------------------------------------------------------------

    def route_board(
        self,
        pcb_path: Path,
        *,
        differential_pairs: tuple[tuple[str, str], ...] = (),
        net_class_map: dict[str, str] | None = None,
        project_dir: Path | None = None,
        undo_stack: Any = None,
    ) -> RoutingOrchestrationResult:
        """Route every net on the board via the configured strategy.

        Single-call batch API (R-7). Parses the PCB, extracts netlist +
        board state, pushes a pre-route snapshot, dispatches each net per
        the strategy, applies results, writes the audit trail, and returns
        a frozen RoutingOrchestrationResult.

        Args:
            pcb_path: Path to the .kicad_pcb file to route.
            differential_pairs: Optional tuples of (pos, neg) diff pair nets.
            net_class_map: Optional net_name -> class label mapping.
            project_dir: Project directory for audit + undo. Defaults to
                pcb_path.parent.
            undo_stack: Optional pre-existing PersistentUndoStack. If None,
                one is created from project_dir.

        Returns:
            RoutingOrchestrationResult with per-net results and audit path.

        Raises:
            ValueError: If strategy output is invalid (H4).
        """
        # Lazy imports to keep module load light and respect the
        # Freerouting-optional pattern.
        from kicad_agent.ir.pcb_ir import PcbIR
        from kicad_agent.ops.persistent_undo import PersistentUndoStack
        from kicad_agent.parser.pcb_native_parser import NativeParser

        start_time = time.time()
        proj = project_dir if project_dir is not None else pcb_path.parent
        stack = undo_stack if undo_stack is not None else PersistentUndoStack(project_dir=proj)

        # 1. Parse PCB via NativeParser -> PcbIR.
        native_board = NativeParser.parse_pcb(pcb_path)
        ir = PcbIR.from_native(native_board)

        # 2. Extract netlist (dict[str, list[Pin]]) + board_state.
        # MD-02/WR-05: use extract_netlist_with_refs to get the real
        # footprint_ref + pad_number instead of synthesizing a fake
        # f"net_{net_name}" that misleads Phase 98 strategies.
        raw_netlist = ir.extract_netlist_with_refs()
        netlist: dict[str, list[Pin]] = {}
        for net_name, pin_tuples in raw_netlist.items():
            pins: list[Pin] = []
            for footprint_ref, pad_number, x, y in pin_tuples:
                pins.append(Pin(
                    footprint_ref=footprint_ref,
                    pad_number=pad_number,
                    x=x,
                    y=y,
                ))
            netlist[net_name] = pins

        bounds = ir.get_board_bounds() or (0.0, 0.0, 0.0, 0.0)
        net_classes = tuple(
            {nc.name for nc in native_board.net_classes} if hasattr(native_board, "net_classes") else set()
        )
        if not net_classes:
            net_classes = ("Default",)
        board_state = BoardState(
            total_nets=len(netlist),
            has_zones=len(native_board.zones) > 0,
            board_bounds=bounds,
            net_classes=net_classes,
        )

        # 3. Push pre-route snapshot via PersistentUndoStack (R3-L2: explicit op_type).
        pre_content = pcb_path.read_text(encoding="utf-8")
        stack.push(pcb_path, pre_content, pre_content, op_type=_OP_TYPE_ROUTE_PRE)

        # 4. Configure strategy with diff pairs + net classes if it's DeterministicStrategy.
        strategy = self._strategy
        if isinstance(strategy, DeterministicStrategy):
            # Build a configured copy if the caller passed kwargs.
            if differential_pairs or net_class_map is not None:
                strategy = DeterministicStrategy(
                    differential_pairs=differential_pairs or strategy.differential_pairs,
                    net_class_map=net_class_map if net_class_map is not None else strategy.net_class_map,
                )

        # 5. Strategize + validate (H4).
        strategy_result = strategy.strategize(board_state, netlist)
        self._validate_strategy_result(strategy_result, netlist)

        # 6. Set up audit log.
        audit_path = proj / ".kicad-agent" / "audit" / f"routing_{int(time.time())}.jsonl"
        audit_log = RoutingAuditLog(audit_path)

        # 7. Dispatch each net per strategy assignment.
        per_net: dict[str, NetRouteResult] = {}
        total_routed = 0
        total_failed = 0

        # Separate nets by backend for batch efficiency.
        astar_nets = [
            n for n in strategy_result.net_priorities
            if strategy_result.router_assignment.get(n) == RouterBackend.ASTAR
        ]
        fr_nets = [
            n for n in strategy_result.net_priorities
            if strategy_result.router_assignment.get(n) == RouterBackend.FREEROUTING
        ]

        # Dispatch A* nets via the in-house pathfinder.
        astar_results = self._dispatch_astar(astar_nets, netlist, board_state)

        # Dispatch Freerouting nets (batch). Falls back to A* on failure.
        fr_results, fr_fallback = self._dispatch_freerouting(fr_nets, pcb_path, netlist, board_state)

        # Merge results + write audit entries.
        for net_name in strategy_result.net_priorities:
            backend = strategy_result.router_assignment.get(net_name, RouterBackend.ASTAR)
            if net_name in astar_results:
                nr = astar_results[net_name]
            elif net_name in fr_results:
                nr = fr_results[net_name]
            else:
                # Net was not routed by either backend.
                nr = NetRouteResult(
                    net_name=net_name,
                    router_used=backend,
                    success=False,
                    route_length_mm=0.0,
                    via_count=0,
                    dispatch_reason="no_route_found",
                    notes="",
                )

            per_net[net_name] = nr
            if nr.success:
                total_routed += 1
            else:
                total_failed += 1

            # Audit entry per net (R-5).
            # WR-03/MD-01: drc_clean=False because no per-net DRC is run here.
            # The board-level DRC is deferred to a later verification phase.
            # Persisting True would misclassify every routed net as DRC-clean
            # in the audit trail — polluting future analysis. The marker
            # [drc_deferred_to_board_level] makes the reason greppable.
            drc_notes = (nr.notes + " [drc_deferred_to_board_level]").strip()
            audit_log.append(RoutingAuditEntry(
                timestamp=now_iso(),
                net_name=net_name,
                router_used=nr.router_used,
                strategy=type(strategy).__name__,
                dispatch_reason=nr.dispatch_reason,
                result="success" if nr.success else "failed",
                route_length_mm=nr.route_length_mm,
                via_count=nr.via_count,
                drc_clean=False,  # not checked at this stage
                notes=drc_notes,
            ))

        # 8. Push post-route snapshot (R3-L2: explicit op_type).
        post_content = pcb_path.read_text(encoding="utf-8")
        stack.push(pcb_path, pre_content, post_content, op_type=_OP_TYPE_ROUTE_POST)

        elapsed = time.time() - start_time
        return RoutingOrchestrationResult(
            per_net=per_net,
            audit_path=audit_path,
            total_routed=total_routed,
            total_failed=total_failed,
            total_rejected=0,
            strategy_used=type(strategy).__name__,
            elapsed_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def _dispatch_astar(
        self,
        nets: list[str],
        netlist: dict[str, list[Pin]],
        board_state: BoardState,
    ) -> dict[str, NetRouteResult]:
        """Route nets via in-house A* pathfinder.

        Returns a dict of NetRouteResult. Nets that fail to route get
        success=False. This is a best-effort dispatch — the caller decides
        whether to fall back.
        """
        from kicad_agent.routing.constraints import RoutingConstraints
        from kicad_agent.routing.graph import RoutingGraph
        from kicad_agent.routing.pathfinder import route_net

        results: dict[str, NetRouteResult] = {}
        if not nets:
            return results

        bounds = board_state.board_bounds
        constraints = RoutingConstraints()
        graph = RoutingGraph(
            board_bounds=bounds,
            obstacles=[],
            constraints=constraints,
        )

        for net_name in nets:
            pins = netlist.get(net_name, [])
            if len(pins) < 2:
                results[net_name] = NetRouteResult(
                    net_name=net_name,
                    router_used=RouterBackend.ASTAR,
                    success=False,
                    route_length_mm=0.0,
                    via_count=0,
                    dispatch_reason="astar:insufficient_pins",
                )
                continue

            source = (pins[0].x, pins[0].y)
            target = (pins[-1].x, pins[-1].y)
            route_result = route_net(graph, source, target, net_name)

            if route_result is not None and route_result.success:
                results[net_name] = NetRouteResult(
                    net_name=net_name,
                    router_used=RouterBackend.ASTAR,
                    success=True,
                    route_length_mm=route_result.length_mm,
                    via_count=0,
                    dispatch_reason="astar:default",
                )
            else:
                results[net_name] = NetRouteResult(
                    net_name=net_name,
                    router_used=RouterBackend.ASTAR,
                    success=False,
                    route_length_mm=0.0,
                    via_count=0,
                    dispatch_reason="astar:no_path_found",
                )
        return results

    def _dispatch_freerouting(
        self,
        nets: list[str],
        pcb_path: Path,
        netlist: dict[str, list[Pin]],
        board_state: BoardState,
    ) -> tuple[dict[str, NetRouteResult], set[str]]:
        """Route nets via Freerouting subprocess (batch).

        C2 correction: import_ses_into_pcb takes (ses_path, pcb_content)
        and returns tuple[str, dict[str, int]]. There is no net_filter.

        Falls back to A* for all Freerouting-dispatched nets if Freerouting
        is unavailable or returns success=False (RESEARCH.md Open Question 3).

        Returns (results_dict, fallback_set) where fallback_set contains nets
        that were retried via A* after Freerouting failed.
        """
        results: dict[str, NetRouteResult] = {}
        fallback: set[str] = set()

        if not nets:
            return results, fallback

        try:
            from kicad_agent.routing.freerouting import (
                is_freerouting_available,
                route_with_freerouting,
            )
        except ImportError:
            # Freerouting module unavailable — fall back entirely.
            fallback.update(nets)
            astar_results = self._dispatch_astar(nets, netlist, board_state)
            for net_name, nr in astar_results.items():
                results[net_name] = NetRouteResult(
                    net_name=nr.net_name,
                    router_used=RouterBackend.ASTAR,
                    success=nr.success,
                    route_length_mm=nr.route_length_mm,
                    via_count=nr.via_count,
                    dispatch_reason="freerouting_unavailable_fallback_astar",
                    notes=nr.notes,
                )
            return results, fallback

        if not is_freerouting_available():
            fallback.update(nets)
            astar_results = self._dispatch_astar(nets, netlist, board_state)
            for net_name, nr in astar_results.items():
                results[net_name] = NetRouteResult(
                    net_name=nr.net_name,
                    router_used=RouterBackend.ASTAR,
                    success=nr.success,
                    route_length_mm=nr.route_length_mm,
                    via_count=nr.via_count,
                    dispatch_reason="freerouting_unavailable_fallback_astar",
                    notes=nr.notes,
                )
            return results, fallback

        # Run Freerouting on the full board (batch — it routes all nets at once).
        output_dir = pcb_path.parent / ".kicad-agent" / "freerouting"
        output_dir.mkdir(parents=True, exist_ok=True)

        fr_result = route_with_freerouting(pcb_path, output_dir=output_dir)

        if not fr_result.success or fr_result.ses_path is None:
            # Freerouting failed — fall back to A* for all dispatched nets.
            logger.warning("Freerouting failed (success=False); falling back to A* for %d nets", len(nets))
            fallback.update(nets)
            astar_results = self._dispatch_astar(nets, netlist, board_state)
            for net_name, nr in astar_results.items():
                results[net_name] = NetRouteResult(
                    net_name=nr.net_name,
                    router_used=RouterBackend.ASTAR,
                    success=nr.success,
                    route_length_mm=nr.route_length_mm,
                    via_count=nr.via_count,
                    dispatch_reason="freerouting_failed_fallback_astar",
                    notes=f"freerouting_stderr={fr_result.stderr[:200]}",
                )
            return results, fallback

        # Import SES into the PCB content.
        from kicad_agent.routing.freerouting import import_ses_into_pcb, parse_ses

        pcb_content = pcb_path.read_text(encoding="utf-8")
        new_content, stats = import_ses_into_pcb(fr_result.ses_path, pcb_content)

        # Pitfall 3 guard: log if SES wire count >> matched wire count.
        matched = stats.get("nets_routed", 0)
        if nets and matched < len(nets) * 0.5:
            logger.warning(
                "Freerouting SES matched %d/%d dispatched nets (>50%% delta) — "
                "some nets may not have routed",
                matched, len(nets),
            )

        # Write the routed content back.
        # CR-02: use atomic_write (temp + fsync + rename) — never bare write_text.
        atomic_write(pcb_path, new_content)

        # Parse the SES to get accurate per-net completion attribution.
        # Freerouting may return success=True even if it only routed a subset
        # of the requested nets. We check which nets actually received wires.
        import math
        ses_text = fr_result.ses_path.read_text(encoding="utf-8")
        ses_parsed = parse_ses(ses_text)
        routed_nets: set[str] = set()
        net_wire_lengths: dict[str, float] = {}
        net_wire_via_counts: dict[str, int] = {}
        for wire in ses_parsed.wires:
            wnet = getattr(wire, "net", "") or ""
            if wnet:
                routed_nets.add(wnet)
                pts = list(getattr(wire, "points", []))
                if len(pts) >= 2:
                    length = sum(
                        math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                        for i in range(len(pts) - 1)
                    )
                    net_wire_lengths[wnet] = net_wire_lengths.get(wnet, 0.0) + length
        for via in ses_parsed.vias:
            vnet = getattr(via, "net", "") or ""
            if vnet:
                net_wire_via_counts[vnet] = net_wire_via_counts.get(vnet, 0) + 1

        segments_added = stats.get("segments", 0)
        vias_added = stats.get("vias", 0)
        for net_name in nets:
            actually_routed = net_name in routed_nets
            results[net_name] = NetRouteResult(
                net_name=net_name,
                router_used=RouterBackend.FREEROUTING,
                success=actually_routed,
                route_length_mm=net_wire_lengths.get(net_name, 0.0),
                via_count=net_wire_via_counts.get(net_name, 0),
                dispatch_reason=(
                    f"freerouting:batch (segments={segments_added}, vias={vias_added})"
                    if actually_routed
                    else "freerouting:batch_no_wire_for_net"
                ),
            )

        return results, fallback

    # ------------------------------------------------------------------
    # H2: Per-net rollback via PcbIR (UUID-based, no regex)
    # ------------------------------------------------------------------

    def rollback_net(
        self,
        pcb_path: Path,
        net_name: str,
        undo_stack: Any = None,
    ) -> None:
        """H2: Surgically remove a single net's routed segments/vias.

        Parses the board via NativeParser, identifies segments and vias
        matching net_name, and applies PcbRawWriter.delete_segment /
        delete_via per UUID value.

        CR-01: joins on the UUID *value* directly (carried by NativeSegment
        and NativeVia since the CR-01 fix), NOT on a positional parent_index.
        The UUID extractor (regex byte-order) and NativeBoard.segments
        (parse-tree DFS) use different traversal orders, so parent_index
        diverges from NativeBoard index on any board with nested segments
        (e.g., inside a (group ...)). The UUID value is the stable identity
        the UUID system was designed to provide.

        Footprint pad net declarations are PRESERVED — only routed tracks
        (segments) and vias at the board level are removed. This replaces
        the unsafe regex approach which corrupts pad definitions because
        ``(net "name")`` appears in both segment and pad contexts.

        Args:
            pcb_path: Path to the .kicad_pcb file.
            net_name: Name of the net whose routed segments/vias to remove.
            undo_stack: Optional PersistentUndoStack for snapshotting the
                rollback. If provided, a pre-rollback snapshot is pushed.

        LO-02 stale-IR warning: this method takes pcb_path (not a PcbIR),
        so any in-memory PcbIR held by the caller (e.g., an
        InteractiveRoutingSession caching _netlist / _suggestions) becomes
        STALE after rollback. Callers that reuse an IR across a rollback
        MUST re-parse via NativeParser.parse_pcb / PcbIR.from_native before
        reading board state again. extract_netlist / get_board_bounds on a
        stale IR will return pre-rollback data.
        """
        from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
        from kicad_agent.parser.pcb_native_parser import NativeParser

        # LO-04: read the raw content ONCE and parse it via parse_pcb_content.
        # Previously this method called NativeParser.parse_pcb(pcb_path) (which
        # reads the file internally) and then separately pcb_path.read_text()
        # for the raw string the writer needs. That doubled the file I/O on
        # every rollback. Caching the single read + parse eliminates the
        # redundancy.
        raw = pcb_path.read_text(encoding="utf-8")

        # Snapshot before rollback if an undo stack is provided.
        if undo_stack is not None:
            undo_stack.push(pcb_path, raw, raw, op_type="rollback_net_pre")

        # 1. Parse the cached content to find segments/vias matching the net.
        board = NativeParser.parse_pcb_content(raw, file_path=str(pcb_path))

        # 2. CR-01: collect UUIDs directly from the parsed segments/vias.
        #    The UUID value is the stable identity — joining on it avoids the
        #    index-divergence bug where extract_uuids parent_index (regex
        #    byte-order) != NativeBoard index (parse-tree DFS).
        seg_uuids = [s.uuid for s in board.segments if s.net_name == net_name and s.uuid]
        via_uuids = [v.uuid for v in board.vias if v.net_name == net_name and v.uuid]

        if not seg_uuids and not via_uuids:
            # Nothing to remove — net has no routed tracks (or they lack UUIDs).
            # No-op.
            return

        # 3. Apply deletions via PcbRawWriter (atomic string operations).
        #    Each delete is a string transform; if a UUID is somehow not
        #    found (stale), we skip it rather than crash.
        for uuid_str in seg_uuids:
            try:
                raw = PcbRawWriter.delete_segment(raw, uuid_str)
            except ValueError:
                logger.debug("Segment UUID %s not found in raw content (stale?)", uuid_str)
        for uuid_str in via_uuids:
            try:
                raw = PcbRawWriter.delete_via(raw, uuid_str)
            except ValueError:
                logger.debug("Via UUID %s not found in raw content (stale?)", uuid_str)

        # 4. Write atomically.
        # CR-02: use atomic_write (temp + fsync + rename) — never bare write_text.
        atomic_write(pcb_path, raw)

        # Snapshot after rollback if undo stack provided.
        # LO-04: post content equals raw (what we just wrote) — no third read.
        if undo_stack is not None:
            undo_stack.push(pcb_path, raw, raw, op_type="rollback_net_post")

    def rollback_full(
        self,
        pcb_path: Path,
        undo_stack: Any,
    ) -> None:
        """Revert to pre-route state via PersistentUndoStack.pop_undo.

        Pops the most recent undo entry for pcb_path and restores its
        pre_content. This is a full rollback (all nets), coarser than
        rollback_net but simpler and guaranteed consistent.

        LO-01 PRE/POST duality: route_board pushes TWO undo entries — a
        "route_board_pre" entry (capturing the pre-route state in BOTH
        pre_content and post_content) and a "route_board_post" entry
        (capturing pre-route in pre_content and post-route in post_content).
        pop_undo returns the most recent (POST) entry first. Restoring
        its pre_content reverts to the PRE-ROUTE state. A second
        rollback_full call pops the PRE entry and restores to the same
        pre-route state (a no-op masked as success). Callers that need
        idempotent rollback should check the PCB content before calling.
        """
        entry = undo_stack.pop_undo(pcb_path)
        if entry is not None:
            # CR-02: use atomic_write (temp + fsync + rename) — never bare write_text.
            atomic_write(pcb_path, entry.pre_content)
