"""How many learners can this service actually hold?

The answer has been "we don't know" for the whole project, listed as a red risk
and left there because a realistic test needs a hundred browsers. That is true
of the *system*. It is not true of the service, which is the part that does the
work and the part that will fall over first — so this measures that, and says
plainly what it does not cover.

What it does: fires /analyze at rising concurrency with a real photograph, and
reports throughput, latency and failures at each level. /analyze is the right
target because it is the endpoint a live session polls on a timer for every
person at once, which makes it the load the service actually sees.

What it does not measure: your application, your database, or the browsers
calling it. A number here is a ceiling for the face pipeline alone, not a
capacity plan for the system it sits in.

Run against a running stack:
    python bench_load.py [http://localhost:9000] [key]
"""
from __future__ import annotations

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
LEVELS = [1, 2, 4, 8, 16, 32]
REQUESTS_PER_LEVEL = 48


def a_real_face() -> bytes:
    """A photograph, not a blank frame.

    Using a frame with no face in it would measure the detector's early exit
    and nothing else — which is exactly the mistake that let 48 tests pass
    while enrolment was broken.
    """
    for candidate in sorted(HERE.glob("tests/faces-public/*/*.jpg")):
        return candidate.read_bytes()
    raise SystemExit("no reference photograph found; run fetch-reference-faces.py")


def one_call(client: httpx.Client, base: str, key: str, image: bytes) -> tuple[float, bool]:
    """One request, and whether it actually worked.

    Checking the body rather than only the status is not fussiness. The first
    version of this posted JSON to an endpoint that takes a multipart upload,
    every request was refused in under a millisecond, and it would have
    reported 427 requests per second — a number that was entirely false and
    looked like good news.
    """
    started = time.monotonic()
    try:
        response = client.post(f"{base}/analyze", timeout=120,
                               headers={"X-Face-Key": key},
                               files={"image": ("frame.jpg", image, "image/jpeg")})
        ok = response.status_code == 200 and response.json().get("ok") is True
    except httpx.HTTPError:
        ok = False
    return time.monotonic() - started, ok


def run_level(base: str, key: str, image: str, concurrency: int) -> dict:
    timings: list[float] = []
    failures = 0

    with httpx.Client() as client:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for elapsed, ok in pool.map(
                    lambda _: one_call(client, base, key, image),
                    range(REQUESTS_PER_LEVEL)):
                timings.append(elapsed)
                failures += 0 if ok else 1
        wall = time.monotonic() - started

    timings.sort()
    return {
        "concurrency": concurrency,
        "median": statistics.median(timings),
        # p95 rather than the mean: the learner who waits longest is the one
        # who complains, and an average hides them.
        "p95": timings[int(len(timings) * 0.95) - 1],
        "slowest": timings[-1],
        "throughput": REQUESTS_PER_LEVEL / wall,
        "failures": failures,
    }


if __name__ == "__main__":
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9000").rstrip("/")
    key = sys.argv[2] if len(sys.argv) > 2 else "dev-local-secret-change-me"

    image = a_real_face()
    # Bail out rather than benchmark a broken call: throughput measured on
    # rejected requests is worse than no measurement.
    with httpx.Client() as probe:
        _, works = one_call(probe, base, key, image)
    if not works:
        raise SystemExit("the first /analyze call failed — fix that before measuring")

    lines = [
        "face-service /analyze under load",
        f"{REQUESTS_PER_LEVEL} requests per level, one real photograph, {base}",
        "",
        "conc   median      p95   slowest   req/s   failed",
    ]

    rows = []
    for level in LEVELS:
        row = run_level(base, key, image, level)
        rows.append(row)
        lines.append(
            f"{row['concurrency']:4d}  {row['median']:6.2f}s  {row['p95']:6.2f}s"
            f"  {row['slowest']:6.2f}s  {row['throughput']:6.1f}  {row['failures']:6d}")
        print(lines[-1], flush=True)

    best = max(rows, key=lambda r: r["throughput"])
    peak = best["throughput"]
    total_failures = sum(row["failures"] for row in rows)

    # Two figures from the same number, and the flattering one is the wrong
    # one to plan with.
    #
    # A monitored lesson polls /analyze on a timer, so it costs one request per
    # learner per interval — cheap. Face enrolment runs the active-liveness
    # challenge, which polls several times a second for as long as the learner
    # is completing it, so it costs a few requests per second per learner. The
    # same service therefore carries hundreds of people watching a lesson and
    # only a handful enrolling, and it is the handful that decides how many can
    # start a session at once.
    presence_interval = 120
    watching = int(peak * presence_interval)
    enrolling = max(1, int(peak / 3))

    lines += [
        "",
        f"peak throughput {peak:.1f} req/s at concurrency {best['concurrency']}",
        "",
        f"  watching a monitored lesson   ~{watching} learners",
        f"      one request each per {presence_interval}s presence check",
        "",
        f"  enrolling a face at once      ~{enrolling} learners",
        "      the liveness challenge polls a few times a second, per learner,",
        "      for as long as it takes them to turn their head",
        "",
        "Enrolment is the constraint, and it is the number to plan around: a",
        "hundred people starting an exam together are all enrolling at once.",
        "",
        # Read off this run rather than written into the prose. The first
        # version quoted the numbers from the run it was written during, and
        # they were wrong by the next one — a report that misquotes its own
        # table is worse than one with no commentary.
        f"Latency is the reason, not failures: {total_failures} requests failed"
        f" across all {len(rows)} levels,",
        f"but p95 went from {rows[0]['p95']:.2f}s alone to"
        f" {rows[-1]['p95']:.2f}s at {rows[-1]['concurrency']} in flight, and a",
        "liveness challenge waiting that long between frames cannot be finished.",
        "",
        "Ceiling for the face pipeline only. Your application, your database",
        "and the browsers calling it are not in this measurement, and the",
        "service was sharing a machine with other work while it ran. Treat it",
        "as an order of magnitude, not a capacity plan.",
    ]

    report = "\n".join(lines) + "\n"

    # Printed in full rather than written to a fixed path. This usually runs
    # inside the service container, where the project's reports directory is
    # not mounted — writing there produced a file nobody could find, and then
    # an error when the parent did not exist either. The caller redirects.
    print()
    print(report, end="")

    for candidate in [HERE / "reports", HERE.parent / "reports"]:
        if candidate.is_dir():
            (candidate / "FACE-LOAD.txt").write_text(report, encoding="utf-8")
            break
