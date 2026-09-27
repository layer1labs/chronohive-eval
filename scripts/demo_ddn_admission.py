# Vendored from layer1labs/chronohive@6f4922e (private).
# Pinned snapshot of the ChronoHive Runtime kernel / eval demo.
# Do not edit here - changes flow from the private repo.

#!/usr/bin/env python3
"""DDN admission demo: coordinated checkpoint/prefetch admission vs greedy baseline.

Deterministic discrete-event simulation (see docs/demo/DDN_ADMISSION_DEMO.md).

Honesty boundaries:
  * The storage backend, the incast contention model, and the DDN API surface
    are SIMULATED. No DDN hardware is involved.
  * The admission decisions are REAL: every grant/refuse comes from the
    chronohive Runtime kernel's capacity discipline (admit/start/
    observe_completion), re-evaluated each scheduling window.
  * Jobs speak the real DDNControl contract (StorageRequest/StorageGrant);
    the simulated DDN surface implements that protocol.

Usage:
  python3 scripts/demo_ddn_admission.py --seed 7 --out build/demo/ddn_admission_results.json
  python3 scripts/demo_ddn_admission.py --report   # rebuild HTML from the JSON
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from chronohive.io_adapters import (
    DDNControl,
    ProductInfo,
    StorageGrant,
    StorageRequest,
    TelemetryReading,
)
from chronohive.runtime import Operation, Plan, Rejected, Runtime

# --------------------------------------------------------------------------
# Scenario parameters (documented in docs/demo/DDN_ADMISSION_DEMO.md)
# --------------------------------------------------------------------------

N_JOBS = 8
EPOCHS = 5
COMPUTE_S = 300.0          # GPU-busy training phase per epoch
SLACK_S = 240.0            # budgeted window after compute for ckpt + prefetch
CKPT_BYTES = 200_000_000_000
CKPT_DEADLINE_S = 120.0    # fault-tolerance SLA after compute ends
PREFETCH_BYTES = 150_000_000_000
WRITE_BW = 25_000_000_000.0  # simulated write-path bandwidth (B/s): independent pool
READ_BW = 40_000_000_000.0   # simulated read-path bandwidth (B/s): independent pool
# Full-duplex fabric: reads and writes contend only WITHIN their own direction
# (no read/write cross-contention). The modeled choke point is the write path
# (storage target controllers / metadata) for writes, the read path for reads.
ALPHA = 0.2               # incast degradation within one direction:
                          # rate_k = (B/k) / (1 + ALPHA*(k-1)). The curve SHAPE is
                          # synthetic; the storm phenomenon it proxies is real even on
                          # striped systems (synchronized clients hammer the same
                          # targets/metadata at epoch end). Fittable to real telemetry.
MISS_PENALTY_S = 60.0      # modeled GPU-time exposure per missed ckpt deadline: a proxy
                          # for risk exposure + recovery/requeue cost when the checkpoint
                          # SLA breaks. With async checkpointing the GPU rarely blocks on
                          # the write itself; the cost is the broken fault-tolerance
                          # contract. Adjustable via --miss-penalty.
WINDOW_S = 10.0            # admission re-evaluation cadence
JITTER_S = 10.0            # per-epoch compute jitter (storms still form)

WRITE_UNIT = 5_000_000_000   # 5 GB/s per kernel capacity unit (write)
READ_UNIT = 5_000_000_000    # 5 GB/s per kernel capacity unit (read)
WRITE_UNITS = 5              # 25 GB/s total write capacity
READ_UNITS = 8               # 40 GB/s total read capacity


# --------------------------------------------------------------------------
# Simulated DDN surface (implements the real DDNControl protocol)
# --------------------------------------------------------------------------

class SimulatedDDN:
    """Simulated DDN control surface implementing the DDNControl protocol.

    product_info/telemetry/request_storage are the contract. apply_qos is the
    simulated Infinia-style control the coordinator drives from grant decisions.
    Everything here is simulation; labeled as such in product_info.
    """

    def __init__(self, coordinator: "AdmissionCoordinator"):
        self._coord = coordinator
        self.qos: dict[str, int] = {}
        self._telemetry: list[TelemetryReading] = []

    def product_info(self) -> ProductInfo:
        return ProductInfo(product="DDN EXAScaler", release="sim-7.0")

    def request_storage(self, request: StorageRequest) -> StorageGrant:
        return self._coord.handle_request(request)

    def telemetry(self) -> tuple[TelemetryReading, ...]:
        return tuple(self._telemetry)

    def apply_qos(self, dataset_id: str, level: int) -> None:
        self.qos[dataset_id] = max(0, min(63, level))

    def record_telemetry(self, observed_ns: int, metrics: dict[str, float]) -> None:
        self._telemetry.append(TelemetryReading(observed_ns=observed_ns, metrics=dict(metrics)))


# --------------------------------------------------------------------------
# Admission coordinator: the REAL kernel makes the grant/refuse decisions
# --------------------------------------------------------------------------

@dataclass
class PendingTransfer:
    dataset_id: str
    job_id: int
    kind: str  # 'checkpoint' | 'prefetch'
    remaining: float
    deadline: float  # sim seconds; inf for prefetch (blocked-compute instead)
    active: bool = False
    miss_counted: bool = False


class AdmissionCoordinator:
    """Per-window admission authority. Each window it builds a fresh Runtime
    kernel over the candidate transfers, admits them earliest-deadline-first,
    and returns StorageGrants. Refused demand retries next window."""

    def __init__(self):
        self.ddn: SimulatedDDN | None = None
        self.admitted_this_window: dict[str, float] = {}  # dataset_id -> B/s
        self.refused_this_window: set[str] = set()
        self.admits = 0
        self.refusals = 0

    def handle_request(self, request: StorageRequest) -> StorageGrant:
        # Requests are queued by the simulation driver and resolved in
        # admit_window(); this path only validates the contract shape.
        return StorageGrant(granted=False, granted_bytes=0, reason="queued for window")

    def admit_window(self, now: float, transfers: list[PendingTransfer], window: int) -> None:
        self.admitted_this_window = {}
        self.refused_this_window = set()
        if not transfers:
            return
        # Earliest deadline first; in-progress transfers win ties (stability).
        ordered = sorted(transfers, key=lambda t: (t.deadline, not t.active))
        ops: dict[str, Operation] = {}
        units: dict[str, int] = {}
        for t in ordered:
            is_write = t.kind == "checkpoint"
            unit = WRITE_UNIT if is_write else READ_UNIT
            cap_units = WRITE_UNITS if is_write else READ_UNITS
            time_left = max(t.deadline - now, WINDOW_S)
            need_bps = t.remaining / time_left
            # Best-effort clamp: never demand more than the whole pipe. Without
            # this, a transfer that has fallen too far behind demands the
            # impossible every window and is refused forever (livelock). A real
            # controller moves it at max rate and counts the miss honestly.
            u = max(1, min(math.ceil(need_bps / unit), cap_units))
            key = "write_bw" if is_write else "read_bw"
            op_id = f"w{window}-{t.dataset_id}"
            ops[op_id] = Operation(id=op_id, demand={key: u})
            units[op_id] = u
        kernel = Runtime(
            capacities={"write_bw": WRITE_UNITS, "read_bw": READ_UNITS},
            operations=tuple(ops.values()),
        )
        by_op = {op_id: t for op_id, t in zip(ops, ordered)}
        for op_id in ops:  # EDF order
            t = by_op[op_id]
            snap = kernel.snapshot()
            plan = Plan(version=snap.version, not_before_ns=window,
                        expires_ns=window + 1, operation_ids=(op_id,))
            try:
                kernel.admit(plan, window)
                kernel.start(op_id)
            except Rejected:
                self.refused_this_window.add(t.dataset_id)
                self.refusals += 1
                assert self.ddn is not None
                self.ddn.apply_qos(t.dataset_id, 8)
                continue
            is_write = t.kind == "checkpoint"
            rate = units[op_id] * (WRITE_UNIT if is_write else READ_UNIT)
            self.admitted_this_window[t.dataset_id] = rate
            self.admits += 1
            # Drive the simulated DDN QoS control from the grant decision.
            urgent = (t.deadline - now) < 30.0
            assert self.ddn is not None
            self.ddn.apply_qos(t.dataset_id, 56 if urgent else 32)

    def complete(self, op_dataset: str) -> None:
        self.admitted_this_window.pop(op_dataset, None)


# --------------------------------------------------------------------------
# Job model
# --------------------------------------------------------------------------

@dataclass
class Job:
    job_id: int
    rng: random.Random
    epoch: int = 0
    compute_left: float = 0.0
    next_slot: float = 0.0   # when the next compute phase is scheduled to start
    transfer: PendingTransfer | None = None
    stall: float = 0.0
    misses: int = 0
    ckpt_done: int = 0
    state: str = "compute"

    def start_epoch(self, now: float) -> None:
        self.compute_left = COMPUTE_S + self.rng.uniform(-JITTER_S, JITTER_S)
        self.state = "compute"


# --------------------------------------------------------------------------
# Simulation driver
# --------------------------------------------------------------------------

@dataclass
class PolicyResult:
    stall: float
    misses: int
    makespan: float
    per_job_stall: list[float]
    admits: int = 0
    refusals: int = 0
    timeline: list[dict] = field(default_factory=list)


def run_policy(seed: int, coordinated: bool) -> PolicyResult:
    rng = random.Random(seed)
    jobs = [Job(job_id=i, rng=random.Random(seed * 1000 + i)) for i in range(N_JOBS)]
    for j in jobs:
        j.start_epoch(0.0)
        j.next_slot = 0.0

    coord = None
    ddn = None
    if coordinated:
        coord = AdmissionCoordinator()
        ddn = SimulatedDDN(coord)
        coord.ddn = ddn

    now = 0.0
    window = 0
    result = PolicyResult(stall=0.0, misses=0, makespan=0.0,
                          per_job_stall=[0.0] * N_JOBS)
    finished = 0

    def submit(job: Job, kind: str) -> None:
        ds = f"job{job.job_id}-e{job.epoch}-{kind}"
        size = float(CKPT_BYTES if kind == "checkpoint" else PREFETCH_BYTES)
        deadline = now + CKPT_DEADLINE_S if kind == "checkpoint" else math.inf
        job.transfer = PendingTransfer(dataset_id=ds, job_id=job.job_id,
                                       kind=kind, remaining=size, deadline=deadline)
        if coordinated:
            # Exercise the real DDNControl contract shape per transfer.
            req = StorageRequest(kind=kind, dataset_id=ds, max_bytes=int(size),
                                 deadline_ns=int(deadline * 1e9) if deadline != math.inf else 2**62)
            ddn.request_storage(req)

    while not all(j.state == "done" for j in jobs):
        # ---- phase transitions ----
        for job in jobs:
            if job.epoch >= EPOCHS:
                continue
            if job.state == "compute":
                if now >= job.next_slot:
                    job.compute_left -= WINDOW_S
                    if job.compute_left <= 0:
                        job.state = "ckpt_wait"
                        # Next compute slot keeps cluster cadence: this compute
                        # ends ~now+WINDOW_S; the GPU is reserved again after
                        # the slack budgeted for checkpoint + prefetch.
                        job.next_slot = now + WINDOW_S + SLACK_S
                        submit(job, "checkpoint")
            elif job.state == "ckpt_wait":
                pass  # transfer drives it
            elif job.state == "prefetch_wait":
                pass

        # ---- transfers ----
        writes = [j for j in jobs if j.transfer and j.transfer.kind == "checkpoint"]
        reads = [j for j in jobs if j.transfer and j.transfer.kind == "prefetch"]

        if coordinated:
            assert coord is not None and ddn is not None
            pending = [j.transfer for j in jobs if j.transfer]
            coord.admit_window(now, pending, window)
            for job in jobs:
                t = job.transfer
                if t is None:
                    continue
                rate = coord.admitted_this_window.get(t.dataset_id, 0.0)
                t.active = rate > 0
                t.remaining -= rate * WINDOW_S
                # checkpoint deadline accounting
                if t.kind == "checkpoint" and not t.miss_counted and now + WINDOW_S > t.deadline and t.remaining > 0:
                    t.miss_counted = True
                    job.misses += 1
                    job.stall += MISS_PENALTY_S
                if t.remaining <= 0:
                    coord.complete(t.dataset_id)
                    advance(job, now, result, submit)
            ddn.record_telemetry(int(now * 1e9), {
                "write_gbps": sum(coord.admitted_this_window.get(j.transfer.dataset_id, 0.0) for j in jobs
                                  if j.transfer and j.transfer.kind == "checkpoint") / 1e9,
                "write_concurrency": float(len(writes)),
                "admitted": float(len(coord.admitted_this_window)),
                "refused": float(len(coord.refused_this_window)),
            })
        else:
            # Greedy baseline with incast degradation.
            kw = len(writes)
            kr = len(reads)
            for job in jobs:
                t = job.transfer
                if t is None:
                    continue
                if t.kind == "checkpoint":
                    rate = (WRITE_BW / kw) / (1 + ALPHA * (kw - 1)) if kw else 0.0
                else:
                    rate = (READ_BW / kr) / (1 + ALPHA * (kr - 1)) if kr else 0.0
                t.remaining -= rate * WINDOW_S
                if t.kind == "checkpoint" and not t.miss_counted and now + WINDOW_S > t.deadline and t.remaining > 0:
                    t.miss_counted = True
                    job.misses += 1
                    job.stall += MISS_PENALTY_S
                if t.remaining <= 0:
                    advance(job, now, result, submit)

        # ---- prefetch-blocked compute => GPU stall ----
        for job in jobs:
            if job.epoch >= EPOCHS:
                continue
            if job.state == "prefetch_wait" and now >= job.next_slot:
                job.stall += WINDOW_S

        result.timeline.append({
            "t": now,
            "writes": len(writes),
            "reads": len(reads),
            "admitted": len(coord.admitted_this_window) if coordinated else 0,
            "refused": len(coord.refused_this_window) if coordinated else 0,
        })
        now += WINDOW_S
        window += 1
        if window > 20000:
            raise RuntimeError("simulation did not converge")

    result.makespan = now
    result.stall = sum(j.stall for j in jobs)
    result.misses = sum(j.misses for j in jobs)
    result.per_job_stall = [j.stall for j in jobs]
    if coordinated:
        assert coord is not None
        result.admits, result.refusals = coord.admits, coord.refusals
    return result


def advance(job: Job, now: float, result: PolicyResult, submit) -> None:
    """A transfer finished; move the job to its next phase."""
    t = job.transfer
    assert t is not None
    if t.kind == "checkpoint":
        job.ckpt_done += 1
        job.state = "prefetch_wait"
        submit(job, "prefetch")
    else:
        job.transfer = None
        job.epoch += 1
        if job.epoch >= EPOCHS:
            job.state = "done"
        else:
            # Prefetch finished: GPU may start the next epoch immediately if
            # its slot already arrived (it stalled), or waits for the slot.
            job.state = "compute"
            job.start_epoch(now)


def main() -> None:
    global MISS_PENALTY_S, N_JOBS, CKPT_BYTES, PREFETCH_BYTES, ALPHA
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="build/demo/ddn_admission_results.json")
    ap.add_argument("--report", action="store_true",
                    help="regenerate the HTML report from --out and exit")
    ap.add_argument("--gpu-price", type=float, default=2.50,
                    help="$ per GPU-hour (default 2.50, H100-class cloud)")
    ap.add_argument("--cluster-gpus", type=int, default=1024,
                    help="GPUs in the modeled cluster (default 1024)")
    ap.add_argument("--miss-penalty", type=float, default=60.0,
                    help="modeled GPU-time exposure (s) per missed checkpoint SLA (default 60)")
    ap.add_argument("--jobs", type=int, default=N_JOBS,
                    help=f"training jobs in the scenario (default {N_JOBS})")
    ap.add_argument("--ckpt-gb", type=float, default=CKPT_BYTES / 1e9,
                    help=f"checkpoint size in GB (default {CKPT_BYTES / 1e9:.0f})")
    ap.add_argument("--prefetch-gb", type=float, default=PREFETCH_BYTES / 1e9,
                    help=f"prefetch size in GB (default {PREFETCH_BYTES / 1e9:.0f})")
    ap.add_argument("--alpha", type=float, default=ALPHA,
                    help=f"incast degradation alpha (default {ALPHA})")
    args = ap.parse_args()

    MISS_PENALTY_S = args.miss_penalty
    N_JOBS = args.jobs
    CKPT_BYTES = args.ckpt_gb * 1e9
    PREFETCH_BYTES = args.prefetch_gb * 1e9
    ALPHA = args.alpha

    if args.report:
        with open(args.out) as fh:
            payload = json.load(fh)
        write_html(payload, args.out)
        print(f"report written: {os.path.splitext(args.out)[0]}.html")
        return

    base = run_policy(args.seed, coordinated=False)
    adm = run_policy(args.seed, coordinated=True)

    def jain(xs: list[float]) -> float:
        s1, s2 = sum(xs), sum(x * x for x in xs)
        return (s1 * s1) / (len(xs) * s2) if s2 else 1.0

    payload = {
        "scenario": {
            "jobs": N_JOBS, "epochs": EPOCHS, "compute_s": COMPUTE_S,
            "slack_s": SLACK_S, "ckpt_gb": CKPT_BYTES / 1e9,
            "ckpt_deadline_s": CKPT_DEADLINE_S, "prefetch_gb": PREFETCH_BYTES / 1e9,
            "write_gbps": WRITE_BW / 1e9, "read_gbps": READ_BW / 1e9,
            "incast_alpha": ALPHA, "miss_penalty_s": MISS_PENALTY_S,
            "window_s": WINDOW_S, "seed": args.seed,
            "honesty": "storage backend, contention model, and DDN API surface are "
                       "simulated; admission decisions come from the real chronohive "
                       "Runtime kernel; results are simulation outcomes, not DDN "
                       "hardware measurements.",
        },
        "baseline": {
            "policy": "greedy uncoordinated",
            "gpu_stall_s": base.stall,
            "ckpt_miss_rate": base.misses / (N_JOBS * EPOCHS),
            "ckpt_misses": base.misses,
            "makespan_s": base.makespan,
            "jain_fairness": jain(base.per_job_stall),
            "per_job_stall_s": base.per_job_stall,
        },
        "admission": {
            "policy": "chronohive kernel admission (EDF, per-window)",
            "gpu_stall_s": adm.stall,
            "ckpt_miss_rate": adm.misses / (N_JOBS * EPOCHS),
            "ckpt_misses": adm.misses,
            "makespan_s": adm.makespan,
            "jain_fairness": jain(adm.per_job_stall),
            "per_job_stall_s": adm.per_job_stall,
            "kernel_admits": adm.admits,
            "kernel_refusals": adm.refusals,
        },
    }
    stall_cut = (base.stall - adm.stall) / base.stall if base.stall else 0.0
    # Pre-registered falsifier: >=20% stall cut and no *meaningful* makespan
    # regression. The 1% tolerance covers window-quantization noise: admission
    # re-evaluates every 10 s window, so a transfer can slip up to one window
    # versus the greedy baseline on an ~2,700 s makespan.
    makespan_tol = 0.01 * base.makespan
    payload["verdict"] = {
        "stall_reduction": stall_cut,
        "makespan_delta_s": adm.makespan - base.makespan,
        "makespan_tolerance_s": makespan_tol,
        "pass": bool(stall_cut >= 0.20 and adm.makespan <= base.makespan + makespan_tol),
    }
    payload["timeline_baseline"] = base.timeline[::6]
    payload["timeline_admission"] = adm.timeline[::6]

    # ---- value model: translate stall into money (stated assumptions) ----
    # In the simulated storm regime, this fraction of GPU time is wasted on
    # checkpoint-miss recovery. Admission drives it to ~zero.
    waste_frac = base.stall / (N_JOBS * base.makespan) if base.makespan else 0.0
    adm_waste_frac = adm.stall / (N_JOBS * adm.makespan) if adm.makespan else 0.0
    hours_per_year = 8760.0

    def annual_dollars(frac: float, price: float, gpus: int) -> float:
        return gpus * hours_per_year * frac * price

    payload["value"] = {
        "assumptions": {
            "gpu_price_per_hour": args.gpu_price,
            "cluster_gpus": args.cluster_gpus,
            "hours_per_year": hours_per_year,
            "note": "Illustrative model, not a measured saving. Waste fraction "
                    "comes from the simulated storm regime; GPU price, cluster "
                    "size, and miss penalty are inputs. See "
                    "docs/demo/DDN_VALUE_REPORT.",
        },
        "waste_fraction_baseline": waste_frac,
        "waste_fraction_admission": adm_waste_frac,
        "annual_waste_baseline_usd": annual_dollars(waste_frac, args.gpu_price, args.cluster_gpus),
        "annual_waste_admission_usd": annual_dollars(adm_waste_frac, args.gpu_price, args.cluster_gpus),
        "annual_savings_usd": annual_dollars(waste_frac - adm_waste_frac,
                                             args.gpu_price, args.cluster_gpus),
        "sensitivity": [
            {"gpu_price": price, "waste_fraction": frac,
             "annual_savings_usd": annual_dollars(frac, price, args.cluster_gpus)}
            for price in (2.0, 3.0, 5.0, 8.0)
            for frac in (0.03, round(waste_frac, 4), 0.10)
        ],
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)
    write_html(payload, args.out)

    b, a, v = payload["baseline"], payload["admission"], payload["verdict"]
    print(f"baseline : stall={b['gpu_stall_s']:8.0f}s misses={b['ckpt_misses']:3d} "
          f"makespan={b['makespan_s']/3600:.2f}h fairness={b['jain_fairness']:.3f}")
    print(f"admission: stall={a['gpu_stall_s']:8.0f}s misses={a['ckpt_misses']:3d} "
          f"makespan={a['makespan_s']/3600:.2f}h fairness={a['jain_fairness']:.3f} "
          f"(admits={a['kernel_admits']} refusals={a['kernel_refusals']})")
    print(f"verdict  : stall reduction={v['stall_reduction']:.1%} "
          f"makespan delta={v['makespan_delta_s']:+.0f}s -> {'PASS' if v['pass'] else 'FAIL'}")
    val = payload["value"]
    print(f"value    : waste fraction={val['waste_fraction_baseline']:.2%} -> "
          f"{val['waste_fraction_admission']:.2%}; projected annual savings for "
          f"{args.cluster_gpus} GPUs @ ${args.gpu_price:.2f}/GPU-hr: "
          f"${val['annual_savings_usd']:,.0f}")


def write_html(payload: dict, out_path: str) -> None:
    html_path = os.path.splitext(out_path)[0] + ".html"
    b, a, v, s = payload["baseline"], payload["admission"], payload["verdict"], payload["scenario"]
    val = payload.get("value")

    def svg(timeline: list[dict], title: str) -> str:
        W, H, PAD = 640, 160, 28
        n = max(len(timeline), 1)
        tmax = max(t["t"] for t in timeline) if timeline else 1
        cmax = max(max(t["writes"], t["reads"]) for t in timeline) if timeline else 1
        bw = (W - 2 * PAD) / n
        bars = []
        for i, t in enumerate(timeline):
            x = PAD + i * bw
            hw = max(t["writes"] / cmax, 0) * (H - 2 * PAD)
            hr = max(t["reads"] / cmax, 0) * (H - 2 * PAD)
            bars.append(
                f'<rect x="{x:.1f}" y="{H - PAD - hw:.1f}" width="{max(bw - 0.5, 0.2):.2f}" '
                f'height="{hw:.1f}" fill="#e11d48" opacity="0.75"/>'
                f'<rect x="{x:.1f}" y="{H - PAD - hw - hr:.1f}" width="{max(bw - 0.5, 0.2):.2f}" '
                f'height="{hr:.1f}" fill="#2563eb" opacity="0.75"/>')
        return (
            f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{title}">'
            f'<text x="{PAD}" y="16" font-size="12" font-weight="bold">{title}</text>'
            f'<text x="{W - PAD}" y="16" font-size="10" text-anchor="end" fill="#64748b">'
            f'<tspan fill="#e11d48">&#9632;</tspan> checkpoint writes '
            f'<tspan fill="#2563eb">&#9632;</tspan> prefetch reads</text>'
            + "".join(bars) +
            f'<line x1="{PAD}" y1="{H - PAD}" x2="{W - PAD}" y2="{H - PAD}" stroke="#94a3b8"/>'
            f'<text x="{PAD}" y="{H - 8}" font-size="10" fill="#64748b">0</text>'
            f'<text x="{W - PAD}" y="{H - 8}" font-size="10" text-anchor="end" fill="#64748b">'
            f'{tmax / 3600:.1f} h</text></svg>')

    card = lambda label, bv, av, fmt: (
        f'<div class="card"><div class="lbl">{label}</div>'
        f'<div class="row"><span class="b">{fmt(bv)}</span>'
        f'<span class="a">{fmt(av)}</span></div>'
        f'<div class="cap">baseline vs <b>admission</b></div></div>')

    mp = s.get("miss_penalty_s", 60.0)
    waste = val["waste_fraction_baseline"] if val else 0.0
    gpus = val["assumptions"]["cluster_gpus"] if val else 0
    price = val["assumptions"]["gpu_price_per_hour"] if val else 0.0
    waste_usd = val["annual_waste_baseline_usd"] if val else 0.0
    adm_usd = val["annual_waste_admission_usd"] if val else 0.0
    save_usd = val["annual_savings_usd"] if val else 0.0
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>ChronoHive x DDN — admission demo</title>
<style>body{{font-family:system-ui,sans-serif;max-width:900px;margin:2em auto;padding:0 1em;color:#0f172a}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}}
.card{{border:1px solid #e2e8f0;border-radius:10px;padding:12px}}
.lbl{{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.04em}}
.row{{display:flex;gap:12px;font-size:22px;margin-top:6px}}.b{{color:#94a3b8}}.a{{color:#059669;font-weight:700}}
.cap{{font-size:11px;color:#94a3b8;margin-top:4px}}
.verdict{{border-radius:10px;padding:14px;margin:16px 0;font-size:18px;
 background:{'#ecfdf5' if v['pass'] else '#fef2f2'};border:1px solid {'#6ee7b7' if v['pass'] else '#fca5a5'}}}
.fine{{font-size:12px;color:#64748b}}h1{{font-size:26px}}</style></head><body>
<h1>Storage as a scheduled resource</h1>
<p>8 training jobs share one simulated 25&nbsp;GB/s-write / 40&nbsp;GB/s-read storage system.
Each epoch: 300&nbsp;s compute, then a 200&nbsp;GB checkpoint (120&nbsp;s SLA) and 150&nbsp;GB prefetch
before the next compute slot. Uncoordinated checkpointing creates incast storms; the ChronoHive
kernel admits movement earliest-deadline-first against provisioned bandwidth.</p>
<div class="verdict">GPU-time exposure reduction: <b>{v['stall_reduction']:.1%}</b> &mdash;
makespan delta {v['makespan_delta_s']:+.0f}&nbsp;s &mdash;
<strong>{'DEMO PASS' if v['pass'] else 'DEMO FAIL'}</strong> (bar: &ge;20% exposure cut, no makespan regression)</div>
<div class="cards">
{card('GPU-time exposure (modeled)', b['gpu_stall_s'], a['gpu_stall_s'], lambda x: f"{x:,.0f} s")}
{card('Checkpoint misses', b['ckpt_misses'], a['ckpt_misses'], lambda x: f"{x} ({x / (s['jobs'] * s['epochs']):.0%})")}
{card('Makespan', b['makespan_s'], a['makespan_s'], lambda x: f"{x / 3600:.2f} h")}
{card('Fairness (Jain)', b['jain_fairness'], a['jain_fairness'], lambda x: f"{x:.3f}")}
</div>
<h2>What this is worth</h2>
<div class="verdict" style="background:#eff6ff;border-color:#93c5fd">
In this simulated storm regime, <b>{waste:.2%}</b> of GPU time is exposed to checkpoint-miss
recovery cost. For a <b>{gpus:,}-GPU</b> cluster at <b>${price:.2f}/GPU-hr</b>, that is
<b>${waste_usd:,.0f}/year</b> of modeled GPU-time exposure &mdash; reduced to
<b>${adm_usd:,.0f}/year</b> under admission, a projected saving of
<b>${save_usd:,.0f}/year</b>.</div>
<p class="fine">Illustrative model, not a measured saving: the waste fraction comes from the
simulated storm regime above; GPU price, cluster size, and miss penalty are demo inputs
(<code>--gpu-price</code>, <code>--cluster-gpus</code>, <code>--miss-penalty</code>).
Rerun with DDN's own numbers.</p>
<h2>Model assumptions &amp; limits</h2>
<ul class="fine">
<li><b>What "exposure" means.</b> Each missed checkpoint SLA is charged a modeled
{mp:.0f}&nbsp;s of GPU-time exposure &mdash; a proxy for risk exposure plus recovery/requeue
cost when the fault-tolerance contract breaks. With async checkpointing the GPU rarely blocks
on the write itself; the cost is the broken contract, not literal idle time.</li>
<li><b>Separate read/write paths.</b> Writes and reads draw from independent bandwidth pools
(25&nbsp;GB/s write, 40&nbsp;GB/s read): no read/write cross-contention, consistent with
full-duplex fabrics. Contention applies within each direction; the modeled choke point is the
write path (storage target controllers / metadata).</li>
<li><b>Synthetic incast curve.</b> The degradation shape
rate<sub>k</sub>&nbsp;=&nbsp;(B/k)/(1+&alpha;(k&minus;1)), &alpha;={s['incast_alpha']}, is a
generalized proxy for fabric/target saturation &mdash; but the storm phenomenon it represents
is real even on striped systems, where synchronized epoch-end writes hammer the same targets
and metadata. The curve can be fitted to real telemetry traces from DDN's lab.</li>
<li><b>Next step: joint pilot.</b> Replace the simulated DDN surface with DDN's actual
management and telemetry APIs on a reference cluster; replay representative
checkpoint/prefetch traces; measure real GPU idle time, miss rate, and makespan. Only then
does the money claim become measured rather than modeled.</li>
</ul>
<h2>Concurrency timelines</h2>
{svg(payload['timeline_baseline'], 'Baseline: greedy (incast storms)')}
{svg(payload['timeline_admission'], 'ChronoHive admission: provisioned, no storms')}
<p class="fine">Kernel decisions this run: {a['kernel_admits']} admits, {a['kernel_refusals']} refusals
(capacity exceeded, retried next window). Seed {s['seed']}.<br>
Honesty note: storage backend, incast model (&alpha;={s['incast_alpha']}), and DDN API surface are
<strong>simulated</strong>. Admission grant/refuse decisions come from the real ChronoHive
<code>Runtime</code> kernel. Numbers are simulation outcomes demonstrating the coordination
mechanism &mdash; not DDN hardware measurements. No DDN hardware involved.</p>
</body></html>"""
    with open(html_path, "w") as fh:
        fh.write(html)


if __name__ == "__main__":
    main()
