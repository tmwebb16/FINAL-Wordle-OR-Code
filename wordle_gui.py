"""Desktop interface for the existing Wordle optimizer."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

import main as game
from second_guesses import SECOND_GUESSES

BG = "#101719"
CARD = "#1b2528"
TEXT = "#ecf3ee"
MUTED = "#9aadaa"
COLORS = ("#435056", "#b28b32", "#4f8964")


class WordleApp:
    def __init__(self, root):
        self.root = root
        root.title("Wordle Optimizer")
        root.geometry("800x780")
        root.minsize(720, 740)
        root.configure(bg=BG)
        self.events = queue.Queue()
        self.generation = 0
        self.busy = False
        self.progress_timer = None
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Horizontal.TProgressbar", troughcolor=CARD, background=COLORS[2], borderwidth=0)
        shell = tk.Frame(root, bg=BG, padx=36, pady=24)
        shell.pack(fill="both", expand=True)
        top = tk.Frame(shell, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="WORDLE / OPTIMIZER", bg=BG, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(side="left")
        self.button(top, "New game", self.reset, CARD).pack(side="right")
        tk.Label(shell, text="Make every guess count.", bg=BG, fg=TEXT, font=("Segoe UI", 25, "bold")).pack(anchor="w", pady=(16, 4))
        tk.Label(shell, text="Play the suggested word in Wordle, then match its tile colors here.", bg=BG, fg=MUTED, font=("Segoe UI", 11)).pack(anchor="w")
        self.meta = tk.Label(shell, bg=BG, fg="#89bb9a", font=("Segoe UI", 11, "bold"))
        self.meta.pack(anchor="w", pady=(18, 12))
        board = tk.Frame(shell, bg=BG)
        board.pack()
        self.tiles = []
        for row in range(4):
            cells = []
            for col in range(5):
                tile = tk.Button(board, text="", width=3, height=1, font=("Segoe UI", 23, "bold"),
                                 bg=CARD, fg=TEXT, activeforeground=TEXT, activebackground=COLORS[0],
                                 relief="flat", borderwidth=0, cursor="hand2",
                                 command=lambda r=row, c=col: self.cycle(r, c))
                tile.grid(row=row, column=col, padx=5, pady=5, ipadx=6, ipady=5)
                cells.append(tile)
            self.tiles.append(cells)
        tk.Label(shell, text="Click a tile to cycle:  gray  >  yellow  >  green", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(pady=(12, 10))
        self.submit_button = self.button(shell, "Submit feedback", self.submit, COLORS[2])
        self.submit_button.pack(fill="x")
        self.status = tk.Label(shell, text="", bg=BG, fg=TEXT, font=("Segoe UI", 11),
                               wraplength=670, justify="left", anchor="w")
        self.status.pack(fill="x", pady=(10, 4))
        self.progress = ttk.Progressbar(shell, mode="indeterminate")
        bottom = tk.Frame(shell, bg=BG)
        self.progress_anchor = bottom
        bottom.pack(fill="x")
        tk.Label(bottom, text="POSSIBLE ANSWERS", bg=BG, fg=MUTED, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.candidates_label = tk.Label(shell, bg=BG, fg=MUTED, font=("Segoe UI", 10),
                                         wraplength=670, justify="left", anchor="nw")
        self.candidates_label.pack(fill="both", expand=True, pady=(8, 0))
        root.bind("<Return>", lambda event: self.submit())
        self.reset()
        root.after(100, self.poll)

    def button(self, parent, text, command, color):
        return tk.Button(parent, text=text, command=command, bg=color, fg=TEXT,
                         activebackground="#365445", activeforeground=TEXT, relief="flat", borderwidth=0,
                         font=("Segoe UI", 10, "bold"), padx=16, pady=9, cursor="hand2")

    def reset(self):
        self.generation += 1
        self.busy = False
        self.finished = False
        self.turn = 0
        self.candidates = list(game.S)
        self.first_feedback = None
        self.guess = "rance"
        self.observed = [0] * 5
        for row in self.tiles:
            for tile in row:
                tile.configure(text="", bg=CARD)
        self.status.configure(text="Match all five colors, then submit. Press Enter to submit, too.", fg=TEXT)
        self.show_guess()
        self.update_progress()

    def show_guess(self):
        for col, letter in enumerate(self.guess.upper()):
            self.tiles[self.turn][col].configure(text=letter, bg=COLORS[0])
        self.meta.configure(text=f"GUESS {self.turn + 1} OF 4     /     {len(self.candidates):,} possible answers")
        preview = ", ".join(word.upper() for word in self.candidates[:24])
        if len(self.candidates) > 24:
            preview += f"  ... +{len(self.candidates) - 24:,} more"
        self.candidates_label.configure(text=preview)
        self.submit_button.configure(state="normal")

    def cycle(self, row, col):
        if self.finished or self.busy or row != self.turn:
            return
        self.observed[col] = (self.observed[col] + 1) % 3
        self.tiles[row][col].configure(bg=COLORS[self.observed[col]])

    def submit(self):
        if self.finished or self.busy:
            return
        observed = tuple(self.observed)
        if observed == (2, 2, 2, 2, 2):
            self.finish(f"Solved in {self.turn + 1} guesses. Nicely done!")
            return
        candidates = game.nextState(self.candidates, self.guess, list(observed))
        if not candidates:
            self.status.configure(text="No listed answer matches. Check the colors, or start a new game to correct earlier feedback.", fg="#edbc72")
            return
        self.candidates = candidates
        if self.turn == 0:
            self.first_feedback = observed
        if self.turn == 3:
            self.candidates_label.configure(text=", ".join(word.upper() for word in candidates))
            self.finish("Four-guess limit reached. Remaining answers are shown below.")
            return
        self.turn += 1
        self.observed = [0] * 5
        if len(candidates) == 1:
            self.guess = candidates[0]
        elif self.turn == 1 and self.first_feedback in SECOND_GUESSES:
            self.guess = SECOND_GUESSES[self.first_feedback]
        else:
            self.busy = True
            self.submit_button.configure(state="disabled")
            self.status.configure(text="Choosing the next word...", fg=MUTED)
            self.update_progress()
            generation, turn = self.generation, self.turn
            def calculate():
                try:
                    _, guess = game.objFunc(turn, candidates)
                    if guess is None:
                        raise ValueError("The optimizer did not return a guess.")
                    self.events.put(("guess", generation, guess))
                except Exception as error:
                    self.events.put(("error", generation, str(error)))
            threading.Thread(target=calculate, daemon=True).start()
            return
        self.show_guess()
        self.status.configure(text="Match the colors for the new guess.", fg=TEXT)

    def finish(self, text):
        self.finished = True
        self.submit_button.configure(state="disabled")
        self.status.configure(text=text, fg="#89bb9a")

    def update_progress(self):
        if self.busy:
            if self.progress_timer is None and not self.progress.winfo_manager():
                self.progress_timer = self.root.after(500, self.show_progress)
        else:
            if self.progress_timer is not None:
                self.root.after_cancel(self.progress_timer)
                self.progress_timer = None
            self.progress.stop()
            self.progress.pack_forget()

    def show_progress(self):
        self.progress_timer = None
        if self.busy:
            self.progress.pack(fill="x", pady=(0, 10), before=self.progress_anchor)
            self.progress.start(15)

    def poll(self):
        try:
            while True:
                kind, generation, payload = self.events.get_nowait()
                if generation == self.generation:
                    self.busy = False
                    if kind == "guess":
                        self.guess = payload
                        self.show_guess()
                        self.status.configure(text="Match the colors for the new guess.", fg=TEXT)
                    else:
                        self.finished = True
                        self.status.configure(text=f"Could not choose a guess: {payload}. Start a new game to retry.", fg="#edbc72")
                self.update_progress()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)


def main():
    root = tk.Tk()
    WordleApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
