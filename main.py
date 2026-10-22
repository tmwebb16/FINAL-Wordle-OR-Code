from pathlib import Path

RESOURCE_DIR = Path(__file__).resolve().parent

with open(RESOURCE_DIR / "wordle-answers-alphabetical.txt", "r") as file:
    S = [line.strip() for line in file]

with open(RESOURCE_DIR / "wordle-allowed-guesses.txt", "r") as file:
    guesses = [line.strip() for line in file]
A = sorted(set(guesses) | set(S))

def feedback(word, guess):
    word = word.upper()
    guess = guess.upper()

    feedback = [0] * 5
    rem = list(word)

    for i in range(5):
        if guess[i] == word[i]:
            feedback[i] = 2
            rem[i] = None

    for i in range(5):
        if feedback[i] == 0 and guess[i] in rem:
            feedback[i] = 1
            rem.remove(guess[i])

    return feedback

def nextState(set, guess, obs_feedback):
    next_state = []

    for word in set:
        if obs_feedback == feedback(word, guess):
            next_state.append(word)

    return next_state

def reward(set, guess):
    if guess in set:
        return 1/len(set)
    else:
        return 0


def probNext(current_set, next_set):
    return len(next_set)/len(current_set)


def termCond(t, set):
    if t < 4 and len(set) == 1:
        return 1
    
    if t == 4:
        return 0

    return None

def objFunc(t, current_set):
    terminal = termCond(t, current_set)
    if terminal is not None:
        return terminal, None

    if t == 3:
        return 1/len(current_set), current_set[0]
    
    best_val = 0
    best_word = None

    for guess in A:
        rew = reward(current_set, guess)
        future_val = 0
        seen_feedback = set()

        for word in current_set:
            result = tuple(feedback(word, guess))
            if result == (2, 2, 2, 2, 2):
                continue
            if result in seen_feedback:
                continue

            seen_feedback.add(result)
            next_set = nextState(current_set, guess, list(result))
            next_val, _ = objFunc(t + 1, next_set)
            p = probNext(current_set, next_set)

            future_val += p * next_val

        val = rew + future_val

        if val > best_val:
            best_val = val
            best_word = guess

    return best_val, best_word


def main():
    from second_guesses import SECOND_GUESSES, STARTING_WORD

    print("Wordle optimizer - aim to solve within four guesses")
    print("Play the suggested word, then enter its five feedback digits.")
    print("0 = gray, 1 = yellow, 2 = green. Example: 01200")
    print("Enter Q at any prompt to quit.\n")
    try:
        while True:
            current_set = list(S)
            first_feedback = None
            for t in range(4):
                if len(current_set) == 1:
                    best_word = current_set[0]
                elif t == 0:
                    best_word = STARTING_WORD
                elif t == 1:
                    best_word = SECOND_GUESSES.get(first_feedback)
                    if best_word is None:
                        _, best_word = objFunc(t, current_set)
                else:
                    print("Choosing the next word...", flush=True)
                    _, best_word = objFunc(t, current_set)

                print(f"\nGuess {t + 1}/4: {best_word.upper()}")
                print(f"Possible answers: {len(current_set)}")
                while True:
                    entered = input("Feedback (five digits, or Q): ").strip().lower()
                    if entered == "q":
                        return
                    entered = "".join(entered.split())
                    if len(entered) != 5 or any(c not in "012" for c in entered):
                        print("Enter exactly five digits using only 0, 1, and 2.")
                        continue
                    observed = tuple(int(c) for c in entered)
                    if observed == (2, 2, 2, 2, 2):
                        break

                    next_set = nextState(current_set, best_word, list(observed))
                    if not next_set:
                        print("No listed answer matches.")
                        continue
                    break

                if observed == (2, 2, 2, 2, 2):
                    print(f"Solved in {t + 1} guesses!")
                    break

                current_set = next_set
                if t == 0:
                    first_feedback = observed
            else:
                print("The four-guess target was not reached.")
                print("Remaining answers: " + ", ".join(current_set))

            if input("\nStart another game? (Y/N): ").strip().lower() != "y":
                return
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
