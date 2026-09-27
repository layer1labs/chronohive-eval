# Vendored from layer1labs/chronohive@6f4922e (private).
# Pinned snapshot of the ChronoHive Runtime kernel / eval demo.
# Do not edit here - changes flow from the private repo.

"""Single-writer reference admission kernel; not a CPSC solver or LF runtime."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping, Protocol


def natural(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f'{name} must be a nonnegative integer')


def resources(values: Mapping[str, int]) -> Mapping[str, int]:
    copied = dict(values)
    for key, value in copied.items():
        if not isinstance(key, str) or not key:
            raise ValueError('resource names must be nonempty strings')
        natural(value, key)
    return MappingProxyType(copied)


@dataclass(frozen=True, order=True)
class Tag:
    time_ns: int
    microstep: int = 0

    def __post_init__(self) -> None:
        natural(self.time_ns, 'time_ns')
        natural(self.microstep, 'microstep')

    def next_microstep(self) -> Tag:
        return Tag(self.time_ns, self.microstep + 1)


class Status(StrEnum):
    PENDING = 'pending'
    ADMITTED = 'admitted'
    RUNNING = 'running'
    COMPLETE = 'complete'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass(frozen=True)
class Operation:
    id: str
    demand: Mapping[str, int]
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('operation id is required')
        if any(not isinstance(x, str) or not x for x in self.dependencies):
            raise ValueError('dependency ids must be nonempty strings')
        if len(set(self.dependencies)) != len(self.dependencies) or self.id in self.dependencies:
            raise ValueError('duplicate or self dependency')
        object.__setattr__(self, 'demand', resources(self.demand))
        object.__setattr__(self, 'dependencies', tuple(self.dependencies))


@dataclass(frozen=True)
class Plan:
    """Immutable proposal. Validity uses caller-supplied monotonic nanoseconds."""
    version: int
    not_before_ns: int
    expires_ns: int
    operation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ('version', 'not_before_ns', 'expires_ns'):
            natural(getattr(self, name), name)
        if self.expires_ns <= self.not_before_ns:
            raise ValueError('plan validity must be nonempty')
        ids = tuple(self.operation_ids)
        if not ids or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
            raise ValueError('plan must contain distinct operation ids')
        object.__setattr__(self, 'operation_ids', ids)


@dataclass(frozen=True)
class Snapshot:
    version: int
    status: tuple[tuple[str, Status], ...]
    available: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class AuditEvent:
    sequence: int
    action: str
    operation_ids: tuple[str, ...]
    version: int


class ProjectionEngine(Protocol):
    """Future CPSC adapter boundary. Solver results are untrusted proposals."""
    def propose(self, snapshot: Snapshot, now_ns: int) -> Plan: ...


class CPSCAdapter:
    """Unbound adapter: refuses until a real engine model is attached (REQ-009).

    Use chronohive.cpsc_adapter.BoundCPSCAdapter to bind the pinned engine
    (ADR-008); lowering a projected state to a kernel Plan is T010/M2 work.
    """
    def propose(self, snapshot: Snapshot, now_ns: int) -> Plan:
        raise NotImplementedError(
            'CPSC engine not bound: use chronohive.cpsc_adapter.BoundCPSCAdapter '
            'with the pinned engine revision (ADR-008)'
        )


class Rejected(ValueError):
    """The proposed transition is not valid; no admission state was changed."""


class Runtime:
    """In-memory single-owner kernel with explicit completion observations.

    No threads, distributed safety, hard real-time guarantees, dispatch side effects,
    CAS-YAML parsing, or LF semantic compatibility are claimed by this class.
    """
    def __init__(self, capacities: Mapping[str, int], operations: tuple[Operation, ...]):
        self._capacity = resources(capacities)
        self._ops = {op.id: op for op in operations}
        if len(self._ops) != len(operations):
            raise ValueError('duplicate operation id')
        for op in operations:
            if not set(op.dependencies) <= self._ops.keys():
                raise ValueError('unknown dependency')
            if not set(op.demand) <= self._capacity.keys():
                raise ValueError('unknown resource')
        remaining = set(self._ops)
        resolved: set[str] = set()
        while remaining:
            ready = {key for key in remaining if set(self._ops[key].dependencies) <= resolved}
            if not ready:
                raise ValueError('dependency cycle')
            resolved.update(ready)
            remaining.difference_update(ready)
        self._status = {key: Status.PENDING for key in self._ops}
        self._held = {key: 0 for key in self._capacity}
        self._version = 0
        self._audit: list[AuditEvent] = []
        self._last_now = 0

    @property
    def audit(self) -> tuple[AuditEvent, ...]:
        return tuple(self._audit)

    def snapshot(self) -> Snapshot:
        return Snapshot(self._version, tuple(sorted(self._status.items())),
                        tuple(sorted((k, v - self._held[k]) for k, v in self._capacity.items())))

    def _record(self, action: str, ids: tuple[str, ...]) -> None:
        self._version += 1
        self._audit.append(AuditEvent(len(self._audit) + 1, action, ids, self._version))

    def admit(self, plan: Plan, now_ns: int) -> tuple[str, ...]:
        natural(now_ns, 'now_ns')
        if now_ns < self._last_now:
            raise Rejected('clock moved backward')
        if plan.version != self._version:
            raise Rejected('stale plan')
        if not plan.not_before_ns <= now_ns < plan.expires_ns:
            raise Rejected('outside validity interval')
        required = dict.fromkeys(self._capacity, 0)
        for key in plan.operation_ids:
            if self._status.get(key) != Status.PENDING:
                raise Rejected('unknown or nonpending operation')
            op = self._ops[key]
            if any(self._status[x] != Status.COMPLETE for x in op.dependencies):
                raise Rejected('dependency has not completed')
            for resource, units in op.demand.items():
                required[resource] += units
        if any(self._held[k] + units > self._capacity[k] for k, units in required.items()):
            raise Rejected('capacity exceeded')
        # Commit only after validating the complete proposal.
        for key in plan.operation_ids:
            self._status[key] = Status.ADMITTED
        for key, units in required.items():
            self._held[key] += units
        self._last_now = now_ns
        self._record('admit', plan.operation_ids)
        return plan.operation_ids

    def start(self, operation_id: str) -> None:
        if self._status.get(operation_id) != Status.ADMITTED:
            raise Rejected('operation must be admitted before start')
        self._status[operation_id] = Status.RUNNING
        self._record('start', (operation_id,))

    def observe_completion(self, operation_id: str, *, succeeded: bool) -> None:
        if type(succeeded) is not bool:
            raise ValueError('succeeded must be boolean')
        if self._status.get(operation_id) != Status.RUNNING:
            raise Rejected('completion requires running operation')
        self._status[operation_id] = Status.COMPLETE if succeeded else Status.FAILED
        if succeeded:
            self._release(operation_id)
        # Failure is ambiguous: retain capacity until an operator/backend reconciles it.
        self._record('complete' if succeeded else 'fail', (operation_id,))

    def cancel_admitted(self, operation_id: str) -> None:
        if self._status.get(operation_id) != Status.ADMITTED:
            raise Rejected('only an undispatched admitted operation can be cancelled')
        self._status[operation_id] = Status.CANCELLED
        self._release(operation_id)
        self._record('cancel', (operation_id,))

    def _release(self, operation_id: str) -> None:
        for key, units in self._ops[operation_id].demand.items():
            self._held[key] -= units
