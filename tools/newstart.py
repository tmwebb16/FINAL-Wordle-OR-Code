import sys
from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RESOURCE_DIR))

from main import S, A, feedback
import numpy as np
import json
from collections import Counter

def orderedGuesses(current_set):
    counts = Counter(
        letter
        for word in current_set
        for letter in set(word)
    )

    return sorted(
        A,
        key=lambda a: sum(counts[letter] for letter in set(a)),
        reverse=True
    )

table = np.load(RESOURCE_DIR / "feedback_table.npy", mmap_mode="r")

with open(RESOURCE_DIR / "feedback_table_words.json", "r") as file:
    words = json.load(file)

guess_index = {word: i for i, word in enumerate(words["guesses"])}
answer_index = {word: i for i, word in enumerate(words["answers"])}

if sorted(A) != words["guesses"] or S != words["answers"]:
    raise ValueError("Word lists don't match the saved feedback table.")
if table.shape != (len(A), len(S)) or table.dtype != np.uint8:
    raise ValueError("Invalid feedback table shape or dtype.")

def feedbackGroups(current_set, guess):
    groups = {}

    codes = table[guess_index[guess], [answer_index[word] for word in current_set]].tolist()
    for word, result in zip(current_set, codes):

        if result == 242:
            continue

        if result not in groups:
            groups[result] = []

        groups[result].append(word)

    return list(groups.values())


import solver_native as native

memo = {}
best_guesses = {}
lower_bounds = {}
pending = {}
stats = Counter()
checkpoint_hook = None
GUESS_ORDER = orderedGuesses(S)
_config_identity = None
_rows = None
_answer_words = None
_guess_words = None


def _configure():
    global _config_identity, _rows, _answer_words, _guess_words
    identity = (id(GUESS_ORDER), id(guess_index), id(answer_index), id(table))
    if identity != _config_identity:
        _rows = np.array([guess_index[w] for w in GUESS_ORDER], dtype=np.int32)
        _answer_words = {i: w for w, i in answer_index.items()}
        _guess_words = {i: w for w, i in guess_index.items()}
        _config_identity = identity


def answer_ids(current_set):
    return tuple(sorted(answer_index[w] if isinstance(w, str) else int(w) for w in current_set))


def state_key(t, current_set):
    return (t, answer_ids(current_set))


def _store(key, partial_key, best, winner):
    pending.pop(partial_key, None)
    if winner is not None:
        memo[key] = best
        best_guesses[key] = winner
    else:
        lower_bounds[key] = max(lower_bounds.get(key, 0), best)
    return best


def _solve(t, ids, cap=None, progress=None):
    stats['calls'] += 1
    key = (t, ids)
    if cap is not None and cap <= 0:
        return 0
    if key in memo:
        stats['exact_hits'] += 1
        return memo[key] if cap is None else min(cap, memo[key])
    if len(ids) <= 4 - t:
        stats['trivial_states'] += 1
        return 0
    if t == 2 and cap is not None and len(ids) - 243 >= cap:
        stats['cardinality_prunes'] += 1
        lower_bounds[key] = max(lower_bounds.get(key, 0), len(ids) - 243)
        return cap
    if cap is not None and lower_bounds.get(key, 0) >= cap:
        stats['bound_hits'] += 1
        return cap
    partial_key = key if cap is None else ('capped', t, cap, ids)
    if partial_key in pending:
        completed, best, winner, saved_order = pending[partial_key]
        rows = np.asarray(saved_order, dtype=np.int32)
    else:
        completed, best, winner = 0, len(ids) if cap is None else cap, None

        rows = _rows if t == 2 else native.rank(table, ids, _rows)
        saved_order = tuple(map(int, rows))
        pending[partial_key] = (completed, best, winner, saved_order)
    if t == 2:
        start = completed
        while start < len(rows) and best > 0:
            if checkpoint_hook is not None:
                checkpoint_hook()
            if progress is not None:
                progress(t, len(ids), start + 1, len(rows))
            stop = min(start + (8 if start == 0 else 4096), len(rows))
            value, guess = native.last_best(table, ids, rows[start:stop], best)
            stats['third_guess_batches'] += 1
            if guess >= 0:
                best, winner = value, guess
            pending[partial_key] = (stop, best, winner, saved_order)
            start = stop
    elif t == 1 and native.LIB is not None:
        context = native.LIB.second_context()
        try:
            start = completed
            while start < len(rows) and best > 0:
                if checkpoint_hook is not None:
                    checkpoint_hook()
                if progress is not None:
                    progress(t, len(ids), start + 1, len(rows))
                stop = min(start + 32, len(rows))
                value, guess, checked, error = native.second_best(
                    table, ids, rows[start:stop], best,
                    lambda child, limit: _solve(2, child, limit, progress), context)
                if guess >= 0:
                    best, winner = value, guess
                start += checked
                stats['second_guesses'] += checked
                pending[partial_key] = (start, best, winner, saved_order)
                if error is not None:
                    raise error
                if checked == 0 and best > 0:
                    raise RuntimeError('Native second-guess evaluation made no progress')
        finally:
            native.LIB.free_second_context(context)
    else:
        signatures = set()
        for position in range(completed, len(rows)):
            if best == 0:
                break
            if checkpoint_hook is not None:
                checkpoint_hook()
            if progress is not None:
                progress(t, len(ids), position + 1, len(rows))
            guess = int(rows[position])
            stats['second_guesses'] += 1
            groups = native.partition(table, ids, guess)


            children = [g for g in groups if len(g) > 3 - t]
            signature = tuple(sorted(children))
            if signature not in signatures:
                if t == 1 and sum(max(0, len(g) - 243) for g in children) >= best:
                    stats['cardinality_prunes'] += 1
                    pending[partial_key] = (position + 1, best, winner, saved_order)
                    continue
                failures = 0
                for group in sorted(children, key=len, reverse=True):
                    failures += _solve(t + 1, group, best - failures, progress)
                    if failures >= best:
                        break
                if failures < best:
                    best, winner = failures, guess

                signatures.add(signature)
                if len(signatures) > 4096:
                    signatures.clear()  
            else:
                stats['equivalent_skips'] += 1
            pending[partial_key] = (position + 1, best, winner, saved_order)
    return _store(key, partial_key, best, winner)


def minFail(t, current_set, progress=None):
    if t not in (0, 1, 2):
        raise ValueError('minFail supports turns 0, 1, and 2.')
    _configure()
    return _solve(t, answer_ids(current_set), progress=progress)


def cappedFail(t, current_set, cap, progress=None):
    if t not in (0, 1, 2):
        raise ValueError('cappedFail supports turns 0, 1, and 2.')
    _configure()
    return _solve(t, answer_ids(current_set), cap, progress)


def chooseGuess(t, current_set):
    if not current_set:
        raise ValueError('Cannot choose from an empty candidate set.')
    if t not in (0, 1, 2, 3):
        raise ValueError('Invalid turn.')
    if t == 3 or len(current_set) <= 4 - t:
        return current_set[0]
    minFail(t, current_set)
    return _guess_words[best_guesses[state_key(t, current_set)]]


def openingFailures(guess, cutoff=None, progress=None):
    _configure()
    failures = 0
    groups = sorted(native.partition(table, answer_ids(S), guess_index[guess]), key=len, reverse=True)
    for number, group in enumerate(groups, 1):
        if progress is not None:
            progress(guess, number, len(groups), failures, 1, len(group), 0, len(GUESS_ORDER))
        def report(t, size, position, total):
            progress(guess, number, len(groups), failures, t, size, position, total)
        callback = report if progress is not None else None
        failures += _solve(1, group, None if cutoff is None else cutoff - failures, callback)
        if progress is not None:
            progress(guess, number, len(groups), failures, 1, len(group), -1, len(GUESS_ORDER))
        if cutoff is not None and failures >= cutoff:
            return failures, False
    return failures, True
