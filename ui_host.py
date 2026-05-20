"""Standalone Tk HUD process for Jarvis.

This module renders the animated desktop UI and communicates with the
parent process through stdin/stdout message frames.
"""

from __future__ import annotations

import math
import queue
import random
import sys
import threading
import time
import ctypes

import tkinter as tk


class JarvisHUDHost:
    """Render and animate the Jarvis HUD in a dedicated process."""

    def __init__(self) -> None:
        """Initialize window widgets, animation state, and pipe reader."""
        self._incoming: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._running = True
        self._state = "INITIALIZING"
        self._phase = 0.0
        self._width = 960
        self._height = 760
        self._left_labels = [
            "Systems",
            "Memory",
            "Sensors",
            "Navigation",
            "Threat Matrix",
            "Comms",
            "Power Grid",
        ]
        self._stars = [
            {
                "x": random.uniform(0, self._width),
                "y": random.uniform(76, self._height - 200),
                "speed": random.uniform(0.25, 1.25),
                "size": random.choice([1, 1, 2]),
            }
            for _ in range(120)
        ]

        self._root = tk.Tk()
        self._configure_windows_shell_identity()
        self._root.title("J.A.R.V.I.S - Voice Core")
        self._root.configure(bg="#00060A")
        self._root.resizable(False, False)
        self._root.geometry(f"{self._width}x{self._height}+120+40")
        self._root.deiconify()
        self._root.lift()
        self._root.after(120, self._ensure_foreground_window)

        self._canvas = tk.Canvas(
            self._root,
            width=self._width,
            height=self._height,
            bg="#00060A",
            highlightthickness=0,
        )
        self._canvas.place(x=0, y=0)
        self._clock_id = self._canvas.create_text(
            self._width - 32,
            30,
            text="--:--:--",
            fill="#3ED9FF",
            anchor="e",
            font=("Consolas", 16, "bold"),
        )

        self._canvas.create_text(
            self._width // 2,
            30,
            text="J.A.R.V.I.S",
            fill="#3ED9FF",
            font=("Consolas", 28, "bold"),
        )
        self._canvas.create_text(
            self._width // 2,
            56,
            text="Just A Rather Very Intelligent System",
            fill="#1B93B8",
            font=("Consolas", 10),
        )
        self._canvas.create_text(
            self._width // 2,
            14,
            text="NEW YORK",
            fill="#58D7FF",
            font=("Consolas", 14, "bold"),
        )
        self._canvas.create_line(0, 72, self._width, 72, fill="#11495E", width=1)

        log_frame = tk.Frame(
            self._root,
            bg="#03131A",
            highlightbackground="#14566E",
            highlightthickness=1,
        )
        log_frame.place(x=130, y=540, width=700, height=140)

        self._log_text = tk.Text(
            log_frame,
            bg="#03131A",
            fg="#95F0FF",
            insertbackground="#95F0FF",
            borderwidth=0,
            font=("Consolas", 10),
            wrap="word",
            padx=8,
            pady=8,
        )
        self._log_text.pack(fill="both", expand=True)
        self._log_text.configure(state="disabled")
        self._log_text.tag_configure("you", foreground="#ECECEC")
        self._log_text.tag_configure("jarvis", foreground="#5AD8FF")
        self._log_text.tag_configure("err", foreground="#FF6060")
        self._log_text.tag_configure("sys", foreground="#FFB15E")

        self._entry = tk.Entry(
            self._root,
            bg="#001018",
            fg="#95F0FF",
            insertbackground="#95F0FF",
            borderwidth=0,
            highlightbackground="#14566E",
            highlightthickness=1,
            font=("Consolas", 10),
        )
        self._entry.place(x=130, y=690, width=610, height=30)
        self._entry.bind("<Return>", self._on_submit_text)

        self._send_button = tk.Button(
            self._root,
            text="SEND >",
            command=self._on_submit_text,
            bg="#03131A",
            fg="#3ED9FF",
            activebackground="#14566E",
            activeforeground="#00060A",
            borderwidth=0,
            highlightbackground="#14566E",
            highlightthickness=1,
            font=("Consolas", 9, "bold"),
            cursor="hand2",
        )
        self._send_button.place(x=748, y=690, width=82, height=30)

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._reader = threading.Thread(target=self._read_parent_messages, daemon=True)
        self._reader.start()

    def run(self) -> None:
        """Start timed UI loops and run the Tk event loop."""
        self._draw_frame()
        self._pump_events()
        self._root.mainloop()

    def _configure_windows_shell_identity(self) -> None:
        """Give the HUD a stable Windows app identity so it stays visible on the taskbar."""
        if not sys.platform.startswith("win"):
            return
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Jarvis.VoiceCore")
        except Exception:
            pass

    def _ensure_foreground_window(self) -> None:
        """Make the HUD visible and foregrounded after launch."""
        try:
            self._root.deiconify()
            self._root.attributes("-topmost", True)
            self._root.focus_force()
            self._root.after(250, lambda: self._root.attributes("-topmost", False))
        except Exception:
            pass

    def _read_parent_messages(self) -> None:
        """Read state and log frames from parent process stdin."""
        for raw in sys.stdin:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            kind, _, value = line.partition("\t")
            self._incoming.put((kind.upper(), value))
        self._incoming.put(("SHUTDOWN", ""))

    def _on_submit_text(self, _event=None) -> None:
        """Send one typed command back to the parent process."""
        text = self._entry.get().strip()
        if not text:
            return
        self._entry.delete(0, "end")
        self._append_log(f"[YOU] {text}")
        print(f"CMD\t{text}", flush=True)

    def _on_close(self) -> None:
        """Stop animations and tear down the window cleanly."""
        try:
            print("EVENT\tWINDOW_CLOSED", flush=True)
        except Exception:
            pass
        self._running = False
        try:
            self._root.quit()
        except Exception:
            pass
        try:
            self._root.destroy()
        except Exception:
            pass

    def _pump_events(self) -> None:
        """Apply queued parent messages to the visible HUD state."""
        while True:
            try:
                kind, value = self._incoming.get_nowait()
            except queue.Empty:
                break

            if kind == "STATE":
                self._state = value.upper().strip() or "LISTENING"
            elif kind == "LOG":
                self._append_log(value)
            elif kind == "SHOW":
                self._ensure_foreground_window()
            elif kind == "SHUTDOWN":
                self._on_close()
                return

        if self._running:
            self._root.after(40, self._pump_events)

    def _append_log(self, line: str) -> None:
        """Append color-coded lines into the HUD log panel."""
        text = (line or "").strip()
        if not text:
            return

        tag = "sys"
        lower = text.lower()
        if lower.startswith("[you]") or lower.startswith("you:"):
            tag = "you"
        elif lower.startswith("[jarvis]") or lower.startswith("jarvis:"):
            tag = "jarvis"
        elif "[error]" in lower or "failed" in lower:
            tag = "err"

        self._log_text.configure(state="normal")
        self._log_text.insert("end", text + "\n", tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _draw_frame(self) -> None:
        """Render one animation frame for the HUD visuals."""
        if not self._running:
            return

        c = self._canvas
        c.delete("hud_dynamic")

        self._phase += 0.09
        cx = self._width // 2
        cy = 300

        state = self._state
        if state == "SPEAKING":
            color = "#FF9A3A"
            aura = 1.0
        elif state == "THINKING":
            color = "#FFD85A"
            aura = 0.7
        elif state == "LISTENING":
            color = "#30E58A"
            aura = 0.9
        elif state == "MUTED":
            color = "#FF4A7A"
            aura = 0.5
        else:
            color = "#3ED9FF"
            aura = 0.65

        for star in self._stars:
            star["x"] += star["speed"] * (1.6 if state == "SPEAKING" else 0.8)
            if star["x"] > self._width + 4:
                star["x"] = -4
                star["y"] = random.uniform(76, self._height - 200)
                star["speed"] = random.uniform(0.25, 1.25)

            brightness = "#0F4F6A" if star["speed"] < 0.75 else "#31BDE6"
            c.create_rectangle(
                star["x"],
                star["y"],
                star["x"] + star["size"],
                star["y"] + star["size"],
                fill=brightness,
                outline="",
                tags="hud_dynamic",
            )

        for y in (140, 200, 260, 320, 380, 440):
            shift = int(22 * math.sin(self._phase * 0.7 + y * 0.01))
            c.create_line(0, y + shift, self._width, y + shift, fill="#082A3A", width=1, tags="hud_dynamic")

        # Top-left circular widgets inspired by Stark HUD overlays.
        widget_specs = [(96, 130, 56), (178, 136, 42), (244, 138, 34)]
        for idx, (wx, wy, wr) in enumerate(widget_specs):
            pulse = 2 + int(4 * abs(math.sin(self._phase * 1.2 + idx)))
            c.create_oval(wx - wr, wy - wr, wx + wr, wy + wr, outline="#2AA8D2", width=2, tags="hud_dynamic")
            c.create_arc(
                wx - wr + pulse,
                wy - wr + pulse,
                wx + wr - pulse,
                wy + wr - pulse,
                start=(self._phase * 60 + idx * 120) % 360,
                extent=80,
                style="arc",
                outline="#7FE8FF",
                width=2,
                tags="hud_dynamic",
            )
        c.create_text(96, 130, text=time.strftime("%b").upper(), fill="#6FE4FF", font=("Consolas", 10, "bold"), tags="hud_dynamic")
        c.create_text(96, 150, text=time.strftime("%d"), fill="#6FE4FF", font=("Consolas", 24, "bold"), tags="hud_dynamic")
        c.create_text(178, 136, text=time.strftime("%H:%M"), fill="#6FE4FF", font=("Consolas", 14, "bold"), tags="hud_dynamic")
        c.create_text(244, 138, text=time.strftime("%S"), fill="#6FE4FF", font=("Consolas", 12, "bold"), tags="hud_dynamic")

        for i in range(7):
            base = 70 + i * 24
            wobble = math.sin(self._phase * (1.2 + i * 0.1) + i) * (4 + aura * 10)
            radius = base + wobble
            alpha_color = "#0D3F55" if i % 2 else "#125A79"
            c.create_oval(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                outline=alpha_color,
                width=2,
                tags="hud_dynamic",
            )

        sweep_radius = 190
        sweep_angle = (self._phase * 42) % 360
        c.create_arc(
            cx - sweep_radius,
            cy - sweep_radius,
            cx + sweep_radius,
            cy + sweep_radius,
            start=sweep_angle,
            extent=46,
            style="arc",
            outline=color,
            width=3,
            tags="hud_dynamic",
        )
        c.create_line(cx - 230, cy, cx + 230, cy, fill="#0A3142", width=1, tags="hud_dynamic")
        c.create_line(cx, cy - 230, cx, cy + 230, fill="#0A3142", width=1, tags="hud_dynamic")
        for bx, by in ((cx - 220, cy - 220), (cx + 220, cy - 220), (cx - 220, cy + 220), (cx + 220, cy + 220)):
            c.create_line(bx, by, bx + (18 if bx < cx else -18), by, fill="#31BDE6", width=2, tags="hud_dynamic")
            c.create_line(bx, by, bx, by + (18 if by < cy else -18), fill="#31BDE6", width=2, tags="hud_dynamic")

        c.create_rectangle(26, 118, 246, 474, outline="#14566E", fill="#021018", width=1, tags="hud_dynamic")
        c.create_text(42, 136, text="DIAGNOSTICS", fill="#53D4FF", anchor="w", font=("Consolas", 10, "bold"), tags="hud_dynamic")
        for idx, label in enumerate(self._left_labels):
            y = 168 + idx * 42
            lvl = int(20 + 72 * abs(math.sin(self._phase * 0.9 + idx * 0.6)))
            c.create_text(42, y, text=label, fill="#4DB4D0", anchor="w", font=("Consolas", 9), tags="hud_dynamic")
            c.create_rectangle(42, y + 12, 210, y + 20, outline="#12485F", fill="#03131A", width=1, tags="hud_dynamic")
            c.create_rectangle(44, y + 14, 44 + lvl, y + 18, outline="", fill="#2AC7F2", tags="hud_dynamic")

        c.create_rectangle(714, 118, 934, 474, outline="#14566E", fill="#021018", width=1, tags="hud_dynamic")
        c.create_text(730, 136, text="TELEMETRY", fill="#53D4FF", anchor="w", font=("Consolas", 10, "bold"), tags="hud_dynamic")
        c.create_text(730, 168, text=f"Date  {time.strftime('%b %d, %Y')}", fill="#86E8FF", anchor="w", font=("Consolas", 10), tags="hud_dynamic")
        c.create_text(730, 196, text=f"Time  {time.strftime('%H:%M:%S')}", fill="#86E8FF", anchor="w", font=("Consolas", 10), tags="hud_dynamic")
        c.create_text(730, 226, text=f"Mode  {state}", fill=color, anchor="w", font=("Consolas", 10, "bold"), tags="hud_dynamic")
        c.create_text(730, 256, text="Audio  ONLINE", fill="#3DDC8A", anchor="w", font=("Consolas", 10), tags="hud_dynamic")
        c.create_text(730, 286, text="Network  ACTIVE", fill="#3DDC8A", anchor="w", font=("Consolas", 10), tags="hud_dynamic")
        c.create_text(730, 316, text="Security  NOMINAL", fill="#FFC96F", anchor="w", font=("Consolas", 10), tags="hud_dynamic")
        c.create_text(730, 346, text="Weather  13C", fill="#86E8FF", anchor="w", font=("Consolas", 10), tags="hud_dynamic")

        for i in range(3):
            rx = 736 + i * 62
            c.create_oval(rx, 360, rx + 46, 406, outline="#1E6E8A", width=2, tags="hud_dynamic")
            pulse = 4 + int(16 * abs(math.sin(self._phase * (1.1 + i * 0.2))))
            c.create_oval(
                rx + 23 - pulse // 2,
                383 - pulse // 2,
                rx + 23 + pulse // 2,
                383 + pulse // 2,
                fill="#2AC7F2",
                outline="",
                tags="hud_dynamic",
            )

        c.create_text(cx, cy, text="J.A.R.V.I.S", fill="#7FDFFF", font=("Consolas", 24, "bold"), tags="hud_dynamic")
        c.create_text(cx, 470, text=f"o {state}", fill=color, font=("Consolas", 14, "bold"), tags="hud_dynamic")

        bars = 28
        bar_w = 9
        total_w = bars * bar_w
        x0 = cx - total_w // 2
        for i in range(bars):
            if state == "SPEAKING":
                height = random.randint(5, 30)
                bar_color = "#2ED6FF"
            elif state == "LISTENING":
                height = random.randint(4, 16)
                bar_color = "#24C679"
            elif state == "THINKING":
                height = 4 + int(6 * abs(math.sin(self._phase + i * 0.2)))
                bar_color = "#FFCC66"
            else:
                height = 4
                bar_color = "#1E6E8A"

            bx = x0 + i * bar_w
            c.create_rectangle(bx, 496 - height, bx + bar_w - 2, 496, fill=bar_color, outline="", tags="hud_dynamic")

        c.itemconfig(self._clock_id, text=time.strftime("%H:%M:%S"))
        c.create_text(self._width // 2, self._height - 20, text="STARK INDUSTRIES", fill="#2B8FB3", font=("Consolas", 15, "bold"), tags="hud_dynamic")
        c.create_line(100, self._height - 20, 330, self._height - 20, fill="#12485F", width=2, tags="hud_dynamic")
        c.create_line(630, self._height - 20, 860, self._height - 20, fill="#12485F", width=2, tags="hud_dynamic")

        if self._running:
            self._root.after(40, self._draw_frame)


def main() -> None:
    """Run the HUD host process entry point."""
    app = JarvisHUDHost()
    app.run()


if __name__ == "__main__":
    """Launch HUD process when executed directly."""
    try:
        main()
    except Exception as exc:
        print(f"HUD_ERROR\t{exc}", file=sys.stderr, flush=True)
