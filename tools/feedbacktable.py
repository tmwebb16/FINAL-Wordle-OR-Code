from pathlib import Path
import sys

RESOURCE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RESOURCE_DIR))

from main import A, S, feedback
import numpy as np
import json


def getFeedbackTable():
    sorted_A = sorted(A)

    table = np.lib.format.open_memmap(
        RESOURCE_DIR / "feedback_table.npy",
        mode="w+",
        dtype=np.uint8,
        shape=(len(sorted_A), len(S))
    )

    for i, a in enumerate(sorted_A):
        for j, s in enumerate(S):

            result = feedback(s, a)

            code = sum(result[k] * (3 ** k) for k in range(5))

            table[i, j] = code

        if (i + 1) % 500 == 0:
            print(f"Processed {i + 1} / {len(sorted_A)} guesses")
            table.flush()

    table.flush()

    with open(RESOURCE_DIR / "feedback_table_words.json", "w") as file:
        json.dump({"guesses": sorted_A, "answers": S}, file)

    print("Feedback table completed!")

if __name__ == "__main__":
    getFeedbackTable()
