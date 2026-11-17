"""Entry point for the portable Windows application."""
import multiprocessing as mp
import os
import sys


if __name__ == "__main__":
    mp.freeze_support()
    # Some speech libraries expect writable streams even without a console.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")

    if len(sys.argv) > 1 and sys.argv[1] == "--check-package":
        from package_check import main
        main(*sys.argv[2:])
    else:
        from app import SpeechApp, tk
        SpeechApp(tk.Tk()).root.mainloop()
