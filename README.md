# Wordle optimizer

Executable located in \dist

Statistics: 99.26% accuracy, only 18 failed games out of 2,308

Expected Amount of Guesses: 3.6534

This optimizer's goal is to maximize the probability of guessing the word in 4 attempts or less.

# How to use

Enter the word prompted by the optimizer. Click on the respective letters based on the feedback provided by the game.

Yellow = Correct letter, wrong spot
Green = Correct letter, correct spot

After submitting the feedback, a new word will appear. Repeat the process.

OR formulation will be posted soon.

Search, simulation, and verification scripts are in `tools/`. See
[tools/SOLVER_SEARCH.md](tools/SOLVER_SEARCH.md) for commands and checkpoint details.
