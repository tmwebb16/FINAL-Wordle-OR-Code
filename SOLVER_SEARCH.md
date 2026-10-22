# Exact opening-word search

Stop the old process with Ctrl+C and wait for its save to finish. Restart with:

```powershell
py -B search_newstart.py --output newstart_results_v2
```

The first restart migrates `solver_checkpoint.pkl` into
`solver_checkpoint.sqlite3`. The original pickle remains untouched as a backup.
Subsequent runs restore the database, which becomes the current checkpoint.
Do not run two searches against the same output directory concurrently.

Completed opener evaluations still save immediately in `search.json`.
New evaluations include their duration, UTC completion timestamp, session ID,
and exact-cache/bound-hit statistics. They also append to `evaluations.jsonl`.
Older entries retain their original format; missing historical timings cannot
be reconstructed. These records support interval speed comparisons without
depending on terminal scrollback.
Incremental solver saves occur every five minutes, on improvements, and at
exit/Ctrl+C. Only changed cache entries are written, in a SQLite transaction.
Use `--checkpoint-seconds 600` to change the interval. A forced shutdown can
lose work since the last commit; restarting repeats the unfinished guess.

## Optimizations

- Integer answer IDs identify all recursive states. Integer guess IDs identify
  decisions. Public functions still accept word strings.
- A C accelerator compiles automatically using a local GCC or Clang, storing
  its generated library in `.native/`. No extra Python package is required.
  Compiled loops count feedback patterns, build partitions, and score guesses.
  The second-guess loop also runs in C, reusing buffers across candidate guesses
  and looking up third-turn states through the shared Python caches.
  An exact NumPy implementation is used if compilation or loading is unavailable.
  The startup message identifies the selected backend.
- Second guesses are ordered per state by the sum of squared feedback-group
  sizes. Every legal guess remains eligible. Each unfinished state's actual
  order is checkpointed; migrated states retain their original order.
- Guesses producing identical nontrivial child candidate sets are evaluated
  once per state. Feedback labels do not alter the continuation problem.
  Child sets small enough for guaranteed success contribute exactly zero.
- Exact values and capped lower bounds remain separate. Capped results never
  become exact cache entries unless a strictly better feasible choice is found.
- There are at most 243 distinct feedback patterns on a five-letter guess.
  Therefore a third-turn state of size n has at least max(0, n - 243) failures.
  The solver sums this conservative bound over second-guess children to reject
  hopeless guesses before computing their exact continuation values.

The objective is still minimum failures within four guesses, with a uniform
answer list and unrestricted allowed guesses. The fourth guess chooses the
first remaining answer. Ties may choose a different policy; the failure count
is preserved. A complete full-opener search, or a zero-failure result, proves
the best count. A subset search does not otherwise establish global optimality.

## Verification

```powershell
py -B audit_solver.py
```

The audit uses an independent feedback function and exhaustive four-turn solver,
including positive-failure examples, information guesses, cap reuse, checkpoint
interruption, legacy migration, and incremental deletion. It tests real table
samples and full-guess-universe third-turn optima. If saved TENOR games exist,
it independently replays them. All test checkpoints use temporary directories;
live search results are read only.

To test the fallback in a separate PowerShell terminal:

```powershell
$env:WORDLE_NO_NATIVE = '1'
py -B audit_solver.py
```

Performance varies by state. Kernel benchmarks do not establish a total search
runtime or prove that the full search can finish in three hours.
