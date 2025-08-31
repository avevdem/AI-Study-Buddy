"""
AI Study Buddy 
Libraries: opencv-python mediapipe pillow
Folders/files (relative):
  img-src/Bg.jpg
  img-src/cameraBoarders.png
  img-src/Camera.png
  img-src/startButton.jpg
  img-src/stopButton.jpg
  img-src/addingPoints.jpg
Font: Pixelify Sans must be in the system (or change family in PIXEL_FONT_FAMILY).
"""

import time, json, os
from pathlib import Path
from datetime import timedelta

import cv2
import mediapipe as mp
import tkinter as tk
import tkinter.font as tkFont
from tkinter import messagebox
from PIL import Image, ImageTk, ImageDraw

# -------------------- CONFIG --------------------
PROGRESS_FILE = "studybuddy_progress.json"

GRACE_PERIOD_SECONDS = 7
REWARD_INTERVAL_SECONDS = 25*60      
POINTS_PER_INTERVAL = 10

UI_REFRESH_MS = 80
PIXEL_FONT_FAMILY = "Pixelify Sans"

# --- UI LAYOUT CONSTANTS  ---
WINDOW_W, WINDOW_H = 1536, 1024      

FRAME_X, FRAME_Y = 130, 120             
VIDEO_PAD_X, VIDEO_PAD_Y = 20, 20   
# right panel with the score
RIGHT_X = 735
RIGHT_STREAK_Y = 140
RIGHT_POINTS_Y = 210
RIGHT_BEST_Y   = 280

# buttons
START_X, START_Y = 160, 535
STOP_X,  STOP_Y  = 160, 535            
POPUP_X, POPUP_Y = 450, 540            # addingPoints window
CAMICON_OFFSET_X, CAMICON_OFFSET_Y = -70, -12 
# --------------------------------------------------


def load_progress():
    if Path(PROGRESS_FILE).exists():
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_points": 0, "best_streak_seconds": 0, "last_saved": None}


def save_progress(data):
    data["last_saved"] = int(time.time())
    with open(PROGRESS_FILE, "w") as f:
        json.dump(data, f, indent=2)


class StudyBuddyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Study Buddy")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- fonts ---
        self.font_small  = tkFont.Font(family=PIXEL_FONT_FAMILY, size=12)
        self.font_medium = tkFont.Font(family=PIXEL_FONT_FAMILY, size=16, weight="bold")
        self.font_big    = tkFont.Font(family=PIXEL_FONT_FAMILY, size=18, weight="bold")

        # --- progress ---
        self.progress = load_progress()
        self.total_points = int(self.progress.get("total_points", 0))
        self.best_streak_seconds = int(self.progress.get("best_streak_seconds", 0))

        # --- camera ---
        self.cap = cv2.VideoCapture(0)
        if not self.cap.isOpened():
            messagebox.showerror("Camera error", "Could not open the webcam. Make sure it's connected.")
            root.destroy()
            return
        self.mp_face = mp.solutions.face_detection.FaceDetection(min_detection_confidence=0.6)

        # --- state ---
        self.running = False
        self.in_focus = False
        self.last_seen_time = 0.0
        self.last_loop_time = time.time()
        self.current_session_seconds = 0.0
        self.accumulated_since_last_reward = 0.0

        # --- canvas with background image  ---
        self.bg_img_pil = Image.open("img-src/Bg.jpg")
        global WINDOW_W, WINDOW_H
        WINDOW_W, WINDOW_H = self.bg_img_pil.size
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")

        self.canvas = tk.Canvas(self.root, width=WINDOW_W, height=WINDOW_H,
                                bd=0, highlightthickness=0)
        self.canvas.place(x=0, y=0)

        self.bg_img = ImageTk.PhotoImage(self.bg_img_pil)
        self.bg_item = self.canvas.create_image(0, 0, anchor="nw", image=self.bg_img)

        # --- camera frame & video ---
        self.frame_pil = Image.open("img-src/cameraBoarders.png")
        self.frame_w, self.frame_h = self.frame_pil.size
        self.frame_img = ImageTk.PhotoImage(self.frame_pil)
        self.frame_item = self.canvas.create_image(FRAME_X, FRAME_Y, anchor="nw", image=self.frame_img)

        # --- coords of video inside the frame ---
        self.video_x = FRAME_X + VIDEO_PAD_X
        self.video_y = FRAME_Y + VIDEO_PAD_Y
        self.video_w = self.frame_w - 2 * VIDEO_PAD_X
        self.video_h = self.frame_h - 2 * VIDEO_PAD_Y

        self._video_tk = ImageTk.PhotoImage(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        self.video_item = self.canvas.create_image(self.video_x, self.video_y, anchor="nw", image=self._video_tk)

        # --- camera icon (snapshot) ---
        cam_icon_pil = Image.open("img-src/Camera.png")
        self.cam_icon = ImageTk.PhotoImage(cam_icon_pil)
        # cam_icon_x = FRAME_X + self.frame_w + CAMICON_OFFSET_X
        # cam_icon_y = FRAME_Y + CAMICON_OFFSET_Y
        cam_icon_x = 520
        cam_icon_y = 150
        self.cam_item = self.canvas.create_image(cam_icon_x, cam_icon_y, anchor="nw", image=self.cam_icon)
        self.canvas.tag_bind(self.cam_item, "<Button-1>", lambda e: self.export_snapshot())

        # --- right panel text ---
        self.streak_text_label = self.canvas.create_text(RIGHT_X, RIGHT_STREAK_Y,
                                                         text="Current streak:",
                                                         font=self.font_small, fill="#2a2255", anchor="nw")
        self.streak_text_value = self.canvas.create_text(RIGHT_X, RIGHT_STREAK_Y + 30,
                                                         text="00:00:00",
                                                         font=self.font_big, fill="#2a2255", anchor="nw")

        self.points_text_label = self.canvas.create_text(RIGHT_X, RIGHT_POINTS_Y,
                                                         text="Total points:",
                                                         font=self.font_small, fill="#2a2255", anchor="nw")
        self.points_text_value = self.canvas.create_text(RIGHT_X, RIGHT_POINTS_Y + 30,
                                                         text=str(self.total_points),
                                                         font=self.font_medium, fill="#2a2255", anchor="nw")

        self.best_text_label = self.canvas.create_text(RIGHT_X, RIGHT_BEST_Y,
                                                       text="Best streak:",
                                                       font=self.font_small, fill="#2a2255", anchor="nw")
        self.best_text_value = self.canvas.create_text(RIGHT_X, RIGHT_BEST_Y + 30,
                                                       text=self._format_seconds(self.best_streak_seconds),
                                                       font=self.font_small, fill="#2a2255", anchor="nw")

        # --- start / stop as images ---
        self.start_img = ImageTk.PhotoImage(Image.open("img-src/startButton.jpg"))
        self.stop_img  = ImageTk.PhotoImage(Image.open("img-src/stopButton.jpg"))

        self.start_item = self.canvas.create_image(START_X, START_Y, anchor="nw", image=self.start_img)
        self.canvas.tag_bind(self.start_item, "<Button-1>", lambda e: self.start())

        self.stop_item = self.canvas.create_image(STOP_X, STOP_Y, anchor="nw", image=self.stop_img, state="hidden")
        self.canvas.tag_bind(self.stop_item, "<Button-1>", lambda e: self.stop())

        # --- addingPoints popup  ---
        self.popup_bg = ImageTk.PhotoImage(Image.open("img-src/addingPoints.jpg"))
        self.popup_item = self.canvas.create_image(POPUP_X, POPUP_Y, anchor="nw", image=self.popup_bg, state="hidden")
        pw, ph = self.popup_bg.width(), self.popup_bg.height()
        self.popup_text = self.canvas.create_text(POPUP_X + pw//2, POPUP_Y + ph//2,
                                                  text="", font=self.font_small, fill="#ffffff",
                                                  state="hidden", anchor="c")

        # --- UI loop ---
        self.root.after(UI_REFRESH_MS, self._ui_loop)

    # -------------- core logic --------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.last_loop_time = time.time()
        self.current_session_seconds = 0.0
        self.accumulated_since_last_reward = 0.0
        # toggle buttons
        self.canvas.itemconfigure(self.start_item, state="hidden")
        self.canvas.itemconfigure(self.stop_item, state="normal")
        # status
        self._show_popup("Running — looking for face...", ms=1200)

    def stop(self):
        if not self.running:
            return
        self.running = False
        self._end_focus_session()
        # toggle buttons
        self.canvas.itemconfigure(self.stop_item, state="hidden")
        self.canvas.itemconfigure(self.start_item, state="normal")

    def on_close(self):
        try:
            if self.cap and self.cap.isOpened():
                self.cap.release()
        finally:
            self.progress["total_points"] = self.total_points
            self.progress["best_streak_seconds"] = self.best_streak_seconds
            save_progress(self.progress)
            self.root.destroy()

    def _format_seconds(self, secs):
        secs = int(secs)
        return str(timedelta(seconds=secs))

    def _set_texts(self):
        self.canvas.itemconfigure(self.streak_text_value, text=self._format_seconds(self.current_session_seconds))
        self.canvas.itemconfigure(self.points_text_value, text=str(self.total_points))
        self.canvas.itemconfigure(self.best_text_value, text=self._format_seconds(self.best_streak_seconds))

    def _show_popup(self, text, ms=1800):
        self.canvas.itemconfigure(self.popup_item, state="normal")
        self.canvas.itemconfigure(self.popup_text, text=text, state="normal")
        self.root.after(ms, lambda: (self.canvas.itemconfigure(self.popup_item, state="hidden"),
                                     self.canvas.itemconfigure(self.popup_text, state="hidden")))

    def _flash_reward(self, points):
        self._show_popup(f"Nice! +{points} points ✨", ms=2200)

    def _flash_message(self, msg):
        self._show_popup(msg, ms=2200)

    def _end_focus_session(self):
        if self.current_session_seconds > 0:
            if self.current_session_seconds > self.best_streak_seconds:
                self.best_streak_seconds = int(self.current_session_seconds)
                self.progress["best_streak_seconds"] = self.best_streak_seconds
                save_progress(self.progress)
                self._flash_message("New best streak! 🎉")
        self.current_session_seconds = 0.0
        self.accumulated_since_last_reward = 0.0
        self.in_focus = False

    # -------------- UI loop --------------
    def _ui_loop(self):
        now = time.time()
        dt = now - self.last_loop_time
        self.last_loop_time = now

        if self.running:
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.flip(frame, 1)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self.mp_face.process(rgb)

                face_detected = bool(results.detections)
                if face_detected:
                    self.last_seen_time = now
                    if not self.in_focus:
                        self.in_focus = True
                        self._show_popup("Focused ✅", ms=1200)

                    self.current_session_seconds += dt
                    self.accumulated_since_last_reward += dt
                    while self.accumulated_since_last_reward >= REWARD_INTERVAL_SECONDS:
                        self.total_points += POINTS_PER_INTERVAL
                        self.accumulated_since_last_reward -= REWARD_INTERVAL_SECONDS
                        self.progress["total_points"] = self.total_points
                        save_progress(self.progress)
                        self._flash_reward(POINTS_PER_INTERVAL)
                else:
                    if self.in_focus and (now - self.last_seen_time) > GRACE_PERIOD_SECONDS:
                        self._end_focus_session()
                        self._show_popup("You left — streak ended 😴", ms=1600)

                # ---- draw camera into canvas ----
                pil = Image.fromarray(rgb).resize((self.video_w, self.video_h), Image.LANCZOS)
                self._video_tk = ImageTk.PhotoImage(pil)
                self.canvas.itemconfigure(self.video_item, image=self._video_tk)
                self.canvas.coords(self.video_item, self.video_x, self.video_y)

        # renew the nums in the right
        self._set_texts()
        # planning the next tic
        self.root.after(UI_REFRESH_MS, self._ui_loop)

    # -------------- snapshot --------------
    def export_snapshot(self):
        ret, frame = self.cap.read()
        if not ret:
            messagebox.showerror("Snapshot failed", "Could not capture frame from camera.")
            return
        frame = cv2.flip(frame, 1)
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(img)

        w, h = pil.size

        lines = [
            "AI Study Buddy",
            f"Streak: {self._format_seconds(self.current_session_seconds)}",
            f"Total points: {self.total_points}",
            f"Best: {self._format_seconds(self.best_streak_seconds)}",
        ]

        measure_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        measure_draw = ImageDraw.Draw(measure_img)
        boxes = [measure_draw.textbbox((0, 0), line) for line in lines]
        line_heights = [b[3] - b[1] for b in boxes]
        line_widths  = [b[2] - b[0] for b in boxes]
        gap = 5  

        block_w = max(line_widths)
        block_h = sum(line_heights) + gap * (len(lines) - 1) + 5

        text_block = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
        td = ImageDraw.Draw(text_block)
        y = 0
        for i, line in enumerate(lines):
            td.text((0, y), line, fill=(255, 255, 255))
            y += line_heights[i] + gap

        SCALE = 2
        text_scaled = text_block.resize((text_block.width * SCALE, text_block.height * SCALE), Image.NEAREST)

        left_pad = 16
        top_pad  = 12
        bottom_pad = 12
        overlay_h = text_scaled.height + top_pad + bottom_pad
        overlay = Image.new("RGBA", (w, overlay_h), (0, 0, 0, 130))
        pil.paste(overlay, (0, h - overlay_h), overlay)

        pil.paste(text_scaled, (left_pad, h - overlay_h + top_pad), text_scaled)

        out_name = f"studybuddy_snapshot_{int(time.time())}.png"
        pil.save(out_name)

        self._show_popup("Snapshot saved 📸", ms=1200)



if __name__ == "__main__":
    root = tk.Tk()
    app = StudyBuddyApp(root)
    root.mainloop()
