import argparse
from collections import defaultdict
from pathlib import Path
from time import perf_counter

import newstart as solver
from search_newstart import search
from simulate import save_results, simulate


def generate(destination, checkpoint_dir):
    groups = defaultdict(list)
    for answer in solver.S:
        pattern = tuple(solver.feedback(answer, 'tenor'))
        if pattern != (2, 2, 2, 2, 2):
            groups[pattern].append(answer)
    guesses = {}
    expected_failures = 0
    last_update = perf_counter()

    def progress(t, size, position, total):
        nonlocal last_update
        now = perf_counter()
        if now - last_update >= 5:
            print(f'  Turn {t + 1}: {size} candidates, guess {position}/{total}', flush=True)
            last_update = now

    for number, (pattern, candidates) in enumerate(
            sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])), 1):
        print(f'{number}/{len(groups)} feedback {"".join(map(str, pattern))}: '
              f'{len(candidates)} answers', flush=True)
        expected_failures += solver.minFail(1, candidates, progress)
        guesses[pattern] = solver.chooseGuess(1, candidates)
        print(f'  Second guess: {guesses[pattern].upper()}', flush=True)

    print('Verifying generated guesses with main.objFunc across all answers...', flush=True)
    results, summary = simulate(progress=False, starting_word='tenor', second_guesses=guesses)
    for row in results:
        if row['guesses_used'] > 1:
            pattern = tuple(map(int, row['feedback'][0]))
            if guesses[pattern] != row['guesses'][1]:
                raise RuntimeError('Generated table disagrees with simulated second guess.')
    if summary['failed'] != expected_failures:
        raise RuntimeError('Simulation disagrees with optimized failure count.')
    if len(guesses) != len(groups) or not all(word in solver.guess_index for word in guesses.values()):
        raise RuntimeError('Incomplete or invalid second-guess table.')
    save_results(results, summary, checkpoint_dir / 'simulation')
    source = "STARTING_WORD = 'tenor'\n\nSECOND_GUESSES = {\n"
    source += ''.join(f'    {pattern!r}: {guesses[pattern]!r},\n' for pattern in sorted(guesses))
    source += '}\n'
    compile(source, str(destination), 'exec')
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    temporary.write_text(source, encoding='utf-8')
    temporary.replace(destination)
    print(f'Saved {len(guesses)} patterns to {destination}; '
          f'verified {summary["failed"]} failures across {len(results)} answers.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=solver.RESOURCE_DIR / 'second_guesses.py')
    parser.add_argument('--checkpoint-dir', type=Path,
                        default=solver.RESOURCE_DIR / 'tenor_second_guess_results')
    args = parser.parse_args()
    search([], args.checkpoint_dir,
           operation=lambda: generate(args.output, args.checkpoint_dir))


if __name__ == '__main__':
    main()
