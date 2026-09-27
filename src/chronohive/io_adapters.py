# Vendored from layer1labs/chronohive@6f4922e (private).
# Pinned snapshot of the ChronoHive Runtime kernel / eval demo.
# Do not edit here - changes flow from the private repo.
# NOTE (public copy): vendor-specific identifiers from the private source
# were renamed vendor-neutral in this public copy. The contract shape,
# simulation math, and behavior are unchanged.

"""I/O adapter interfaces: storage control and NCCL/CUDA completion.

STATUS (2026-09-25): the CollectiveCompletion (NCCL/CUDA) contract was
validated against real backend observations on a 2-GPU isolated testbed
(see testbed/t013/, evidence at testbed/t013/evidence/).

The StorageControl contract is the integration surface for a storage
system, not a hardware driver: it is defined against a generic
storage-control contract, so no vendor hardware is needed or expected. The
contract is defined here and pinned by mock conformance tests; the
remaining step is confirming its operations map onto a storage vendor's
published product APIs.

Contract summary (see docs/architecture/ADAPTER_INTERFACES.md):

* StorageControl: product/release identification ("confirm actual APIs" as a
  contract), prefetch/checkpoint as admission requests with explicit limits,
  timestamped monotonic telemetry that is observation-only.
* CollectiveCompletion: rank/world membership, submission-is-not-completion,
  backend-observed completion events with ordering enforcement, stale
  membership invalidates outstanding tracking, no synthetic completions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class ProductInfo:
    """The storage product/release an implementation speaks to."""

    product: str
    release: str

    def __post_init__(self) -> None:
        if not self.product or not self.release:
            raise ValueError('product and release must be nonempty')


@dataclass(frozen=True)
class StorageRequest:
    """An admission request for storage movement (prefetch or checkpoint)."""

    kind: str  # 'prefetch' | 'checkpoint'
    dataset_id: str
    max_bytes: int
    deadline_ns: int

    def __post_init__(self) -> None:
        if self.kind not in ('prefetch', 'checkpoint'):
            raise ValueError("kind must be 'prefetch' or 'checkpoint'")
        if not self.dataset_id:
            raise ValueError('dataset_id is required')
        if not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ValueError('max_bytes must be a positive integer')
        if not isinstance(self.deadline_ns, int) or self.deadline_ns < 0:
            raise ValueError('deadline_ns must be a nonnegative integer')


@dataclass(frozen=True)
class StorageGrant:
    """The adapter's answer: granted as requested, capped, or refused."""

    granted: bool
    granted_bytes: int
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.granted_bytes, int) or self.granted_bytes < 0:
            raise ValueError('granted_bytes must be a nonnegative integer')
        if self.granted and self.reason:
            raise ValueError('a granted request carries no refusal reason')
        if not self.granted and not self.reason:
            raise ValueError('a refused request must state why')


@dataclass(frozen=True)
class TelemetryReading:
    """One timestamped observation. Observation only — never control."""

    observed_ns: int
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.observed_ns, int) or self.observed_ns < 0:
            raise ValueError('observed_ns must be a nonnegative integer')


class StorageControl(Protocol):
    """Storage control contract (interface only; see module docstring)."""

    def product_info(self) -> ProductInfo: ...
    def request_storage(self, request: StorageRequest) -> StorageGrant: ...
    def telemetry(self) -> tuple[TelemetryReading, ...]: ...


@dataclass(frozen=True)
class Membership:
    """Collective membership: this rank in a world of `world_size`."""

    rank: int
    world_size: int
    epoch: int  # increments on every membership change

    def __post_init__(self) -> None:
        for name in ('rank', 'world_size', 'epoch'):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')
        if self.rank >= self.world_size:
            raise ValueError('rank must be < world_size')


@dataclass(frozen=True)
class BackendCompletion:
    """A completion event as observed by the backend (never synthesized).

    `backend_seq` is the backend's own sequence number; ordering is enforced
    per communicator: NCCL collectives complete in issue order.
    """

    operation_id: str
    backend_seq: int
    backend_observed_ns: int
    membership_epoch: int

    def __post_init__(self) -> None:
        if not self.operation_id:
            raise ValueError('operation_id is required')
        for name in ('backend_seq', 'backend_observed_ns', 'membership_epoch'):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f'{name} must be a nonnegative integer')


class CompletionRejected(ValueError):
    """A backend completion event failed contract validation."""


class CollectiveCompletion(Protocol):
    """NCCL/CUDA collective completion contract (interface only)."""

    def membership(self) -> Membership: ...
    def submit(self, operation_id: str) -> int:
        """Record a submission; returns the issue sequence. Not completion."""
    def observe_completion(self, event: BackendCompletion) -> str:
        """Validate a backend-observed completion; returns operation_id.

        Raises CompletionRejected on out-of-order, duplicate, or
        stale-membership events. Never synthesizes completion.
        """
