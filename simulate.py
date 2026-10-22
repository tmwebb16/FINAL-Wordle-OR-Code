"""Run every listed answer through the current four-guess strategy."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter

import main as game

GREEN = (2, 2, 2, 2, 2)


def simulate(answers=None, progress=True, starting_word=None, second_guesses=None):
    from second_guesses import SECOND_GUESSES, STARTING_WORD
    starting_word = STARTING_WORD if starting_word is None else starting_word
    second_guesses = SECOND_GUESSES if second_guesses is None else second_guesses
    # Always retain the full candidate universe, even for a subset of targets.
    targets = set(game.S if answers is None else answers)
    unknown = targets.difference(game.S)
    if unknown:
        raise ValueError("Unknown answers: " + ", ".join(sorted(unknown)))
    results = []
    nodes = 0
    started = perf_counter()

    def visit(candidates, active, t, first_feedback, history):
        nonlocal nodes
        nodes += 1
        if len(candidates) == 1:
            guess = candidates[0]
        elif t == 0:
            guess = starting_word
        elif t == 1:
            guess = second_guesses.get(first_feedback)
            if guess is None:
                _, guess = game.objFunc(t, candidates)
        else:
            _, guess = game.objFunc(t, candidates)
        if guess is None:
            raise RuntimeError(f"No guess returned at turn {t + 1}")

        groups = defaultdict(list)
        for answer in candidates:
            groups[tuple(game.feedback(answer, guess))].append(answer)
        for observed, group in groups.items():
            group_targets = active.intersection(group)
            if not group_targets:
                continue
            path = history + [(guess, observed)]
            if observed == GREEN or t == 3:
                for answer in group:
                    if answer in group_targets:
                        results.append({
                            "answer": answer,
                            "solved": observed == GREEN,
                            "guesses_used": t + 1,
                            "guesses": [word for word, _ in path],
                            "feedback": ["".join(map(str, pattern)) for _, pattern in path],
                        })
                if progress:
                    print(f"Completed {len(results)}/{len(targets)} games", flush=True)
            else:
                visit(group, group_targets, t + 1,
                      observed if t == 0 else first_feedback, path)

    if targets:
        visit(list(game.S), targets, 0, None, [])
    results.sort(key=lambda row: row["answer"])
    solved = [row for row in results if row["solved"]]
    summary = {
        "total_games": len(results), "solved": len(solved),
        "failed": len(results) - len(solved),
        "solve_rate": len(solved) / len(results) if results else 0,
        "solved_by_guess": dict(sorted(Counter(row["guesses_used"] for row in solved).items())),
        "average_guesses_when_solved": sum(row["guesses_used"] for row in solved) / len(solved) if solved else None,
        "failed_answers": [row["answer"] for row in results if not row["solved"]],
        "decision_nodes": nodes, "elapsed_seconds": round(perf_counter() - started, 3),
    }
    return results, summary


def save_results(results, summary, output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / "games.csv").open("w", newline="", encoding="utf-8") as file:
        fields = ["answer", "solved", "guesses_used", "guess_1", "guess_2", "guess_3", "guess_4",
                  "feedback_1", "feedback_2", "feedback_3", "feedback_4"]
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = {key: result[key] for key in fields[:3]}
            row.update({f"guess_{i + 1}": word for i, word in enumerate(result["guesses"])})
            row.update({f"feedback_{i + 1}": pattern for i, pattern in enumerate(result["feedback"])})
            writer.writerow(row)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("simulation_results"),
                        help="Directory for games.csv and summary.json")
    parser.add_argument("--answers", nargs="+", help="Optional subset of target answers")
    args = parser.parse_args()
    print("Simulating the current strategy against every requested answer...", flush=True)
    results, summary = simulate(args.answers)
    save_results(results, summary, args.output)
    print(json.dumps(summary, indent=2))
    print(f"Results saved to {args.output.resolve()}")


if __name__ == "__main__":
    main()
