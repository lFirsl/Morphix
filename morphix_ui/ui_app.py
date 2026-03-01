import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox


def find_morphix_exe():
    candidates = [
        os.path.join(os.getcwd(), "dist", "Morphix.exe"),
        os.path.join(os.getcwd(), "Morphix.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


class MorphixUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Morphix")
        self.geometry("560x240")
        self.resizable(False, False)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.size_var = tk.StringVar(value="20")

        self._build_ui()

    def _build_ui(self):
        padding = {"padx": 10, "pady": 6}

        tk.Label(self, text="Input file").grid(row=0, column=0, sticky="w", **padding)
        tk.Entry(self, textvariable=self.input_var, width=50).grid(row=0, column=1, **padding)
        tk.Button(self, text="Browse", command=self.browse_input).grid(row=0, column=2, **padding)

        tk.Label(self, text="Output file").grid(row=1, column=0, sticky="w", **padding)
        tk.Entry(self, textvariable=self.output_var, width=50).grid(row=1, column=1, **padding)
        tk.Button(self, text="Browse", command=self.browse_output).grid(row=1, column=2, **padding)

        tk.Label(self, text="Target size (MB)").grid(row=2, column=0, sticky="w", **padding)
        tk.Entry(self, textvariable=self.size_var, width=10).grid(row=2, column=1, sticky="w", **padding)

        tk.Button(self, text="Compress", command=self.run_compress).grid(
            row=3, column=1, sticky="e", padx=10, pady=12
        )

        self.status = tk.Label(self, text="", fg="#444444")
        self.status.grid(row=4, column=0, columnspan=3, sticky="w", padx=10, pady=6)

    def browse_input(self):
        path = filedialog.askopenfilename(
            title="Select video",
            filetypes=[("Video files", "*.mp4;*.mov;*.mkv;*.avi;*.webm"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                base, ext = os.path.splitext(path)
                self.output_var.set(base + "-morphix-compressed" + (ext or ".mp4"))

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Select output file",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self.output_var.set(path)

    def run_compress(self):
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        size_mb = self.size_var.get().strip()

        if not input_path:
            messagebox.showerror("Morphix", "Please select an input file.")
            return
        if not size_mb:
            messagebox.showerror("Morphix", "Please enter a target size in MB.")
            return

        exe_path = find_morphix_exe()
        if exe_path:
            cmd = [exe_path, input_path, "--max-mb", size_mb]
        else:
            cmd = [sys.executable, "-m", "morphix_core.Morphix", input_path, "--max-mb", size_mb]

        if output_path:
            cmd += ["--output", output_path]

        self.status.config(text="Running compression...")
        try:
            subprocess.Popen(cmd, cwd=os.getcwd())
        except OSError as exc:
            messagebox.showerror("Morphix", f"Failed to start Morphix.\n{exc}")
            self.status.config(text="")
            return

        self.status.config(text="Started. Check the output file when done.")


if __name__ == "__main__":
    app = MorphixUI()
    app.mainloop()
