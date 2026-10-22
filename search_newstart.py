import argparse
from collections import Counter, defaultdict
import json
import hashlib
from solver_checkpoint import Checkpoint
from pathlib import Path
from time import perf_counter, sleep
from datetime import datetime, timezone
import uuid

import newstart as solver
from simulate import save_results


def replace_with_retry(source, destination, attempts=6):
    for attempt in range(attempts):
        try:
            source.replace(destination)
            return True
        except PermissionError:
            if attempt + 1 < attempts:
                sleep(min(0.05 * 2**attempt, 0.5))
    return False


def save_report(output, report):
    temporary = output / f'search.{uuid.uuid4().hex}.tmp'
    temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if replace_with_retry(temporary, output / 'search.json'):
        return
    recovery = output / 'search.recovery.json'
    if not replace_with_retry(temporary, recovery):
        recovery = temporary
    print(f'search.json is locked; progress saved to {recovery.name}. Continuing.', flush=True)


def load_report(output, fingerprint):
    paths = [output / 'search.json', output / 'search.recovery.json', output / 'search.tmp']
    paths.extend(output.glob('search.*.tmp'))
    valid = []
    found = False
    for path in paths:
        if not path.exists():
            continue
        found = True
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
            if (report.get('fingerprint') == fingerprint
                    and report.get('searched') == len(report.get('openers', []))):
                valid.append((report['searched'], path.stat().st_mtime_ns, path, report))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    if not valid:
        if found:
            raise ValueError('No valid search report matches the current inputs. Keep the files for recovery.')
        return None
    _, _, path, report = max(valid, key=lambda item: item[:2])
    if path.name != 'search.json':
        print(f'Recovered {report["searched"]} opener results from {path.name}.', flush=True)
    return report


def evaluate_opener(word, cutoff=None):

    started = perf_counter()
    last_report = started
    group_started = started
    second_position = 0
    print(f'Evaluating {word.upper()}...', flush=True)

    def progress(guess, group, groups, failures, t, size, position, total):
        nonlocal last_report, group_started, second_position
        now = perf_counter()
        boundary = position in (0, -1)
        if position == 0:
            group_started = now
            second_position = 0
        if t == 1:
            second_position = max(0, position - 1)
        if not boundary and now - last_report < 5:
            return
        last_report = now
        percent = 100 * second_position / total if total else 0
        if position == -1:
            status = f'complete (100%); {group}/{groups} groups complete'
        elif position == 0:
            status = 'starting'
        else:
            status = f'{percent:.1f}% second-guess choices scanned (may prune early)'
        print(f'  {guess.upper()} | elapsed {now - started:.0f}s | '
              f'feedback group {group}/{groups} | '
              f'{status}, group elapsed {now - group_started:.1f}s | '
              f'turn {t + 1}, {size} candidates, guess {max(0, position)}/{total} | '
              f'failures from completed groups: {failures} | '
              f'cached states: {len(solver.memo)}', flush=True)

    result = solver.openingFailures(word, cutoff=cutoff, progress=progress)
    print(f'  {word.upper()} evaluated in {perf_counter() - started:.1f}s', flush=True)
    return result


def simulate(starting_word):

    results = []

    def visit(candidates, t, history):
        guess = starting_word if t == 0 else solver.chooseGuess(t, candidates)
        groups = defaultdict(list)
        for answer in candidates:
            pattern = tuple(solver.feedback(answer, guess))
            groups[pattern].append(answer)
        for pattern, group in groups.items():
            path = history + [(guess, ''.join(map(str, pattern)))]
            if pattern == (2, 2, 2, 2, 2) or t == 3:
                for answer in group:
                    results.append(dict(answer=answer, solved=pattern == (2, 2, 2, 2, 2),
                                        guesses_used=t + 1,
                                        guesses=[g for g, _ in path],
                                        feedback=[f for _, f in path]))
            else:
                visit(group, t + 1, path)

    visit(list(solver.S), 0, [])
    results.sort(key=lambda row: row['answer'])
    solved = [row for row in results if row['solved']]
    summary = dict(starting_word=starting_word, total_games=len(results),
                   solved=len(solved), failed=len(results) - len(solved),
                   solve_rate=len(solved) / len(results),
                   solved_by_guess=dict(sorted(Counter(r['guesses_used'] for r in solved).items())),
                   average_guesses_when_solved=(sum(r['guesses_used'] for r in solved) / len(solved)
                                               if solved else None),
                   failed_answers=[r['answer'] for r in results if not r['solved']])
    return results, summary


def search(openers, output, operation=None, checkpoint_seconds=300):

    if checkpoint_seconds <= 0:
        raise ValueError('Checkpoint interval must be positive.')
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps(
        [solver.A, solver.S, solver.GUESS_ORDER, 'solver-checkpoint-v1']
    ).encode()).hexdigest()
    store = Checkpoint(output, fingerprint, solver)
    print('Native acceleration: ' + ('enabled' if solver.native.LIB is not None else 'NumPy fallback'), flush=True)
    last_save = perf_counter()

    def save(force=False):
        nonlocal last_save
        if not force and perf_counter() - last_save < checkpoint_seconds:
            return
        save_started = perf_counter()
        changed = store.save()
        last_save = perf_counter()
        print(f'Checkpoint saved: {changed} changed entries; '
              f'{len(solver.memo)} exact states, {len(solver.pending)} unfinished states; '
              f'{store.path.stat().st_size / 1_000_000:.1f} MB database in '
              f'{last_save - save_started:.2f}s.', flush=True)

    previous_hook = solver.checkpoint_hook
    solver.checkpoint_hook = save
    try:
        if operation is not None:
            return operation()
        return _search(openers, output)
    finally:
        try:
            save(force=True)
        finally:
            solver.checkpoint_hook = previous_hook
            store.close()


def _search(openers, output):
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    session_id = uuid.uuid4().hex
    print('Using known RANCE bound: 18 failures; evaluating RANCE last.', flush=True)
    best_failures = 18
    best_word = 'rance'
    rows = []
    history = []
    fingerprint = hashlib.sha256(json.dumps([solver.A, solver.S]).encode()).hexdigest()
    previous = load_report(output, fingerprint)
    if previous is not None:
        rows = previous['openers']
        history = previous.get('best_history', [])
        best_word = previous['best_starting_word']
        best_failures = previous['best_failures']
        print(f'Resuming {len(rows)} saved opener evaluations.', flush=True)
    candidates = list(dict.fromkeys(word for word in openers if word != 'rance'))
    if 'rance' in openers:
        candidates.append('rance')

    def checkpoint(complete, force_solver=False):
        report = dict(best_starting_word=best_word, best_failures=best_failures,
                      previous_rance_failures=18, fingerprint=fingerprint, best_history=history,
                      searched=len(rows), requested=len(candidates),
                      complete=complete, globally_optimal=(best_failures == 0 or
                          (complete and set(r['word'] for r in rows) >= set(solver.A))),
                      elapsed_seconds=round(perf_counter() - started, 3), openers=rows)
        save_report(output, report)
        if solver.checkpoint_hook is not None:
            solver.checkpoint_hook(force=force_solver)

    checkpoint(False)
    print(f'Current best: {best_word.upper()}, {best_failures} failures', flush=True)
    tried = {r['word'] for r in rows}
    for word in candidates:
        if word in tried:
            continue
        if best_failures == 0:
            break
        before_stats = dict(solver.stats)
        evaluation_started = perf_counter()
        failures, exact = evaluate_opener(word, cutoff=best_failures)
        evaluation_seconds = perf_counter() - evaluation_started
        metrics = {key: solver.stats[key] - before_stats.get(key, 0) for key in solver.stats}
        entry = dict(word=word, failures=failures, exact=exact,
                     evaluation_seconds=round(evaluation_seconds, 6),
                     completed_at_utc=datetime.now(timezone.utc).isoformat(),
                     session_id=session_id, session_elapsed_seconds=round(perf_counter() - started, 6),
                     statistics=metrics)
        rows.append(entry)
        with (output / 'evaluations.jsonl').open('a', encoding='utf-8') as log:
            log.write(json.dumps(dict(completed=len(rows), **entry)) + '\n')
        improved = exact and failures < best_failures
        if improved:
            best_word, best_failures = word, failures
            history.append(dict(word=word, failures=failures))
        checkpoint(False, force_solver=improved)
        print(f'{len(rows)}/{len(candidates)} {word.upper()}: '
              f'{"" if exact else "at least "}{failures}; '
              f'best {best_word.upper()} = {best_failures}; cache {len(solver.memo)}', flush=True)
        print(f'  {evaluation_seconds:.2f}s | exact cache hits: {metrics.get("exact_hits", 0)} | '
              f'bound hits: {metrics.get("bound_hits", 0)} | '
              f'third-guess batches: {metrics.get("third_guess_batches", 0)}', flush=True)
        if improved:
            results, summary = simulate(word)
            if summary['failed'] != failures:
                raise RuntimeError('Simulation disagrees with optimized failure count.')
            save_results(results, summary, output / 'best_words' / word)
            print(f'New best saved: {word.upper()} ({failures} failures); continuing.', flush=True)
    if best_word != 'rance':
        print(f'Simulating {best_word.upper()} across all {len(solver.S)} answers...', flush=True)
        results, summary = simulate(best_word)
        if summary['failed'] != best_failures:
            raise RuntimeError('Simulation disagrees with the optimized failure count.')
        save_results(results, summary, output / 'best_simulation')
    else:
        print('No opener beat the known 18-failure baseline.', flush=True)
    checkpoint(True)
    return best_word, best_failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openers', nargs='+', help='Optional subset; default searches all allowed openers')
    parser.add_argument('--simulate-only', metavar='WORD', help='Simulate a fixed opener without searching')
    parser.add_argument('--output', type=Path, default=solver.RESOURCE_DIR / 'newstart_results')
    parser.add_argument('--checkpoint-seconds', type=float, default=300,
                        help='Seconds between full-cache saves (default: 300); also save on improvements and exit')
    args = parser.parse_args()
    if args.checkpoint_seconds <= 0:
        parser.error('--checkpoint-seconds must be positive')
    openers = [word.lower() for word in args.openers] if args.openers else solver.GUESS_ORDER
    requested = [args.simulate_only.lower()] if args.simulate_only else openers
    unknown = set(requested) - set(solver.A)
    if unknown:
        parser.error('Unknown guesses: ' + ', '.join(sorted(unknown)))
    if args.simulate_only:
        results, summary = simulate(requested[0])
        save_results(results, summary, args.output / requested[0])
        print(json.dumps(summary, indent=2))
    else:
        word, failures = search(openers, args.output, checkpoint_seconds=args.checkpoint_seconds)
        print(f'Best opener: {word.upper()}, {failures}/{len(solver.S)} failures')


if __name__ == '__main__':
    main()
