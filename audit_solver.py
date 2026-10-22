from collections import Counter
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import csv
import json
import random
import hashlib
import pickle

import numpy as np
import newstart as solver
import search_newstart as runner


def score(answer, guess):
    result = [2 if a == g else 0 for a, g in zip(answer, guess)]
    remaining = Counter(a for i, a in enumerate(answer) if result[i] != 2)
    for i, letter in enumerate(guess):
        if result[i] == 0 and remaining[letter]:
            result[i] = 1
            remaining[letter] -= 1
    return tuple(result)


def clear():
    for cache in (solver.memo, solver.best_guesses, solver.lower_bounds, solver.pending):
        cache.clear()


def check_small_universes():
    checks = 0


    answers = [letter + 'aaaa' for letter in 'bcdefg']
    for extra in ([], ['bcdef', 'cdefg', 'ggbbb']):
        guesses = answers + extra
        matrix = np.array([[sum(v * 3**i for i, v in enumerate(score(a, g)))
                            for a in answers] for g in guesses], dtype=np.uint8)

        @lru_cache(None)
        def reference(t, candidates):
            if t == 4:
                return len(candidates)
            values = []
            for guess in guesses:
                groups = {}
                for answer in candidates:
                    pattern = score(answer, guess)
                    if pattern != (2,) * 5:
                        groups.setdefault(pattern, []).append(answer)
                values.append(sum(reference(t + 1, tuple(group)) for group in groups.values()))
            return min(values)

        with patch.multiple(solver, A=guesses, S=answers, GUESS_ORDER=guesses,
                            table=matrix, guess_index={g: i for i, g in enumerate(guesses)},
                            answer_index={a: i for i, a in enumerate(answers)}):
            for size in range(7):
                for candidates in combinations(answers, size):
                    for t in range(3):
                        expected = reference(t, candidates)
                        clear()

                        for cap in range(0, size + 2):
                            assert solver.cappedFail(t, list(candidates), cap) == min(expected, cap)
                            checks += 1
                        assert solver.minFail(t, list(reversed(candidates))) == expected
                        checks += 1
                        key = solver.state_key(t, candidates)
                        assert key not in solver.memo or solver.memo[key] == expected
                        inverse = {i: w for w, i in solver.answer_index.items()}
                        assert all(bound <= reference(k[0], tuple(inverse[i] for i in k[1]))
                                   for k, bound in solver.lower_bounds.items())

            for opener in guesses:
                clear()
                exact, flag = solver.openingFailures(opener)
                with patch.object(solver, 'feedback', side_effect=lambda a, g: list(score(a, g))):
                    _, summary = runner.simulate(opener)
                assert flag and exact == summary['failed']
                checks += 1
    clear()
    return checks


def check_real_table():
    rng = random.Random(20261021)
    for _ in range(5000):
        guess, answer = rng.choice(solver.A), rng.choice(solver.S)
        code = sum(v * 3**i for i, v in enumerate(score(answer, guess)))
        assert code == int(solver.table[solver.guess_index[guess], solver.answer_index[answer]])

    for size in (5, 25, 80):
        candidates = rng.sample(solver.S, size)
        expected = min(size - len({score(a, g) for a in candidates}) for g in solver.GUESS_ORDER)
        clear()
        assert solver.minFail(2, candidates) == expected
        for cap in (1, 3, 17):
            clear()
            assert solver.cappedFail(2, candidates, cap) == min(cap, expected)
    clear()
    candidates = rng.sample(solver.S, 300)
    assert solver.cappedFail(2, candidates, 57) == 57
    assert solver.lower_bounds[solver.state_key(2, candidates)] >= 57
    clear()


def check_resume():
    candidates = random.Random(17).sample(solver.S, 180)
    clear()
    calls = 0

    def interrupt():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt

    with TemporaryDirectory() as folder:
        output = Path(folder)

        def work():


            with patch.object(solver, 'checkpoint_hook', side_effect=interrupt):
                solver.cappedFail(2, candidates, 1)

        try:
            runner.search([], output, operation=work)
        except KeyboardInterrupt:
            pass
        assert solver.pending, 'Test must interrupt an unfinished state'
        clear()
        resumed = runner.search([], output, operation=lambda: solver.cappedFail(2, candidates, 1))
        clear()
        assert resumed == solver.cappedFail(2, candidates, 1)
    clear()


def check_saved_tenor():
    folder = solver.RESOURCE_DIR / 'newstart_results_v2' / 'best_words' / 'tenor'
    if not (folder / 'games.csv').exists():
        return 'not present'
    rows = list(csv.DictReader((folder / 'games.csv').open(encoding='utf-8', newline='')))
    assert len(rows) == len(solver.S)
    assert {r['answer'] for r in rows} == set(solver.S)
    failures = 0
    for row in rows:
        assert row['guess_1'] == 'tenor'
        solved = False
        for turn in range(1, int(row['guesses_used']) + 1):
            guess = row[f'guess_{turn}']
            assert guess in solver.guess_index
            pattern = score(row['answer'], guess)
            assert ''.join(map(str, pattern)) == row[f'feedback_{turn}']
            if pattern == (2,) * 5:
                assert turn == int(row['guesses_used'])
                solved = True
        assert solved == (row['solved'] == 'True')
        failures += not solved
    summary = json.loads((folder / 'summary.json').read_text())
    assert failures == summary['failed'] == 17
    return f'{len(rows)} saved games replayed; {failures} failures confirmed'


def check_legacy_migration():
    from solver_checkpoint import Checkpoint
    candidates = random.Random(31).sample(solver.S, 120)
    key = (2, tuple(sorted(candidates)))
    costs = [len(candidates) - len({score(a, g) for a in candidates})
             for g in solver.GUESS_ORDER[:5]]
    best = min(costs)
    winner = solver.GUESS_ORDER[costs.index(best)]
    fingerprint = hashlib.sha256(json.dumps(
        [solver.A, solver.S, solver.GUESS_ORDER, 'solver-checkpoint-v1']).encode()).hexdigest()
    with TemporaryDirectory() as directory:
        output = Path(directory)
        state = dict(fingerprint=fingerprint, memo={}, best_guesses={}, lower_bounds={},
                     pending={key: (5, best, winner)})
        original = pickle.dumps(state)
        (output / 'solver_checkpoint.pkl').write_bytes(original)
        store = Checkpoint(output, fingerprint, solver)
        assert solver.pending[solver.state_key(2, candidates)][:3] == (
            5, best, solver.guess_index[winner])
        result = solver.minFail(2, candidates)
        assert store.save() > 0
        assert store.save() == 0
        store.close()
        assert (output / 'solver_checkpoint.pkl').read_bytes() == original
        store = Checkpoint(output, fingerprint, solver)
        assert solver.memo[solver.state_key(2, candidates)] == result
        assert not solver.pending
        store.close()
        clear()
        assert solver.minFail(2, candidates) == result
    clear()


def check_reordered_resume():
    answers = [letter + 'aaaa' for letter in 'bcdefg']
    matrix = np.array([[sum(v * 3**i for i, v in enumerate(score(a, g)))
                        for a in answers] for g in answers], dtype=np.uint8)
    with patch.multiple(solver, A=answers, S=answers, GUESS_ORDER=list(reversed(answers)),
                        table=matrix, guess_index={g: i for i, g in enumerate(answers)},
                        answer_index={a: i for i, a in enumerate(answers)}):
        clear()
        with TemporaryDirectory() as directory:
            output = Path(directory)
            child_calls = 0

            def progress(t, size, position, total):
                nonlocal child_calls
                if t == 2:
                    child_calls += 1
                    if child_calls == 2:
                        raise KeyboardInterrupt

            try:
                runner.search([], output, operation=lambda: solver.cappedFail(1, answers, 5, progress))
            except KeyboardInterrupt:
                pass
            key = ('capped', 1, 5, solver.answer_ids(answers))
            assert solver.pending[key][0] == 1
            actual_order = solver.pending[key][3]
            clear()

            def resumed():
                assert solver.pending[key][3] == actual_order
                return solver.cappedFail(1, answers, 5)

            result = runner.search([], output, operation=resumed)


            assert result == 3
            clear()
            assert solver.minFail(1, answers) == result
    clear()


if __name__ == '__main__':
    count = check_small_universes()
    print(f'{count} independent exhaustive/capped/simulation checks passed.', flush=True)
    check_real_table()
    print('5,000 table checks and full-universe third-guess comparisons passed.', flush=True)
    check_resume()
    print('Interrupted checkpoint disk restore matches fresh evaluation.', flush=True)
    check_legacy_migration()
    print('Legacy migration and incremental update/delete checks passed.', flush=True)
    check_reordered_resume()
    print('State-specific guess order survives second-turn interruption and resume.', flush=True)
    print('TENOR: ' + check_saved_tenor(), flush=True)
