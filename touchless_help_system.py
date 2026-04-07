import cv2
import mediapipe as mp
import time
import smtplib
from email.mime.text import MIMEText
from collections import deque
from gpiozero import LED, TonalBuzzer
from gpiozero.tones import Tone

# =========================================================
# GPIO SETUP
# =========================================================
# I matched these pins to the wiring I planned before.
GREEN_LED_PIN = 17
RED_LED_PIN = 27
WHITE_LED_PIN = 22
BUZZER_PIN = 18

green_led = LED(GREEN_LED_PIN)
red_led = LED(RED_LED_PIN)
white_led = LED(WHITE_LED_PIN)
buzzer = TonalBuzzer(BUZZER_PIN)

# =========================================================
# EMAIL SETUP
# =========================================================
# I left email optional so I can test everything safely first.
EMAIL_ENABLED = False

SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your_app_password"
RECEIVER_EMAIL = "caregiver_email@gmail.com"

def send_caregiver_email():
    # I kept this separate so the rest of the system still works even if email is off.
    if not EMAIL_ENABLED:
        print("Email is disabled, so I only showed the caregiver alert locally.")
        return

    try:
        subject = "Caregiver Alert"
        body = "Assistance is needed. The Raspberry Pi touchless help system detected the caregiver gesture."

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECEIVER_EMAIL

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())

        print("Caregiver email sent successfully.")

    except Exception as e:
        print(f"Email failed: {e}")

# =========================================================
# OUTPUT HELPERS
# =========================================================
def all_outputs_off():
    # I use this so only one mode stays active at a time.
    green_led.off()
    red_led.off()
    white_led.off()
    buzzer.stop()

def caregiver_jingle():
    # I made this a short, calm little melody now that I know my buzzer supports tones.
    notes = ["C5", "E5", "G5", "E5", "C5"]
    lengths = [0.16, 0.16, 0.22, 0.16, 0.22]

    for note, length in zip(notes, lengths):
        buzzer.play(Tone(note))
        time.sleep(length)
        buzzer.stop()
        time.sleep(0.04)

def emergency_alarm(duration=3.0):
    # I made this harsher by alternating two high tones quickly.
    start = time.time()

    while time.time() - start < duration:
        buzzer.play(Tone("A5"))
        time.sleep(0.16)
        buzzer.stop()
        time.sleep(0.03)

        buzzer.play(Tone("F5"))
        time.sleep(0.16)
        buzzer.stop()
        time.sleep(0.03)

def light_confirmation_tone():
    # I gave the light action one tiny confirmation tone.
    buzzer.play(Tone("C5"))
    time.sleep(0.08)
    buzzer.stop()

def trigger_caregiver_alert():
    # I want this one to feel calm and clear.
    all_outputs_off()
    green_led.on()
    print("Caregiver notified")
    caregiver_jingle()
    send_caregiver_email()

def trigger_emergency_alert():
    # I want this one to feel urgent and obvious.
    all_outputs_off()
    red_led.on()
    print("Emergency alert activated")
    emergency_alarm(duration=3.0)

def trigger_lights_on():
    # I kept this simple since it is just simulating room lights.
    all_outputs_off()
    white_led.on()
    print("Lights on")
    light_confirmation_tone()

# =========================================================
# STARTUP TEST
# =========================================================
def startup_test():
    # I do this once so I know all the hardware is alive before the camera starts.
    all_outputs_off()

    green_led.on()
    time.sleep(0.20)
    green_led.off()

    red_led.on()
    time.sleep(0.20)
    red_led.off()

    white_led.on()
    time.sleep(0.20)
    white_led.off()

    buzzer.play(Tone("C5"))
    time.sleep(0.12)
    buzzer.stop()

startup_test()

# =========================================================
# MEDIAPIPE SETUP
# =========================================================
mp_drawing = mp.solutions.drawing_utils
mp_hands = mp.solutions.hands

# =========================================================
# CAMERA SETUP
# =========================================================
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# =========================================================
# FPS SETUP
# =========================================================
prev_time = time.time()
fps = 0.0

# =========================================================
# GESTURE HELPERS
# =========================================================
def count_fingers(hand_landmarks, hand_label):
    # I reused the finger logic because it already worked well.
    landmarks = hand_landmarks.landmark
    finger_states = []

    # I handle thumb differently because it points sideways.
    if hand_label == "Right":
        thumb_up = 1 if landmarks[4].x < landmarks[3].x else 0
    else:
        thumb_up = 1 if landmarks[4].x > landmarks[3].x else 0

    finger_states.append(thumb_up)

    finger_tips = [8, 12, 16, 20]
    finger_pips = [6, 10, 14, 18]

    for tip, pip in zip(finger_tips, finger_pips):
        is_up = 1 if landmarks[tip].y < landmarks[pip].y else 0
        finger_states.append(is_up)

    raw_count = sum(finger_states)
    return raw_count, finger_states

def is_open_palm(finger_states):
    # I use all five fingers up for caregiver mode.
    return finger_states == [1, 1, 1, 1, 1]

def is_two_fingers(finger_states):
    # I use the peace sign for lights on.
    return finger_states == [0, 1, 1, 0, 0]

def get_hand_center(hand_landmarks):
    # I use a rough center point so I can track side to side movement.
    landmarks = hand_landmarks.landmark
    x = (landmarks[0].x + landmarks[9].x) / 2.0
    y = (landmarks[0].y + landmarks[9].y) / 2.0
    return x, y

def is_wave_ready(finger_states):
    # I only allow wave detection when the hand is mostly open.
    return sum(finger_states) >= 4

# =========================================================
# STATE VARIABLES
# =========================================================
open_palm_start_time = None
current_mode = "IDLE"

# I keep short motion history so wave detection feels faster.
x_history = deque(maxlen=8)
dx_history = deque(maxlen=7)

last_trigger_time = 0
trigger_cooldown = 2.5

hand_missing_frames = 0

# =========================================================
# MAIN LOOP
# =========================================================
with mp_hands.Hands(
    static_image_mode=False,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7,
    max_num_hands=1
) as hands:

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame")
                break

            frame = cv2.flip(frame, 1)
            frame = cv2.resize(frame, (640, 480))

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = hands.process(rgb_frame)

            hand_found = False
            hand_label = "None"
            finger_states = [0, 0, 0, 0, 0]
            raw_count = 0
            gesture_text = "None"
            open_palm_progress = 0.0
            waving_detected = False
            wave_debug = "x_range=0.00 dir_changes=0"

            now = time.time()

            if results.multi_hand_landmarks and results.multi_handedness:
                hand_found = True
                hand_missing_frames = 0

                hand_landmarks = results.multi_hand_landmarks[0]
                hand_label = results.multi_handedness[0].classification[0].label

                mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS
                )

                raw_count, finger_states = count_fingers(hand_landmarks, hand_label)

                center_x, center_y = get_hand_center(hand_landmarks)

                if len(x_history) > 0:
                    dx = center_x - x_history[-1]
                    dx_history.append(dx)

                x_history.append(center_x)

                # =================================================
                # CAREGIVER, open palm held for 3 seconds
                # =================================================
                if is_open_palm(finger_states):
                    gesture_text = "Open Palm"

                    if open_palm_start_time is None:
                        open_palm_start_time = now

                    open_palm_progress = now - open_palm_start_time

                    if open_palm_progress >= 3.0 and (now - last_trigger_time) >= trigger_cooldown:
                        current_mode = "CAREGIVER"
                        trigger_caregiver_alert()
                        last_trigger_time = time.time()

                else:
                    open_palm_start_time = None

                # =================================================
                # LIGHTS ON, two fingers
                # =================================================
                if is_two_fingers(finger_states):
                    gesture_text = "Two Fingers"

                    if (now - last_trigger_time) >= trigger_cooldown:
                        current_mode = "LIGHTS ON"
                        trigger_lights_on()
                        last_trigger_time = time.time()

                # =================================================
                # EMERGENCY, waving hand
                # =================================================
                # I made this more responsive so it does not wait forever.
                if len(x_history) >= 6 and len(dx_history) >= 5 and is_wave_ready(finger_states):
                    x_range = max(x_history) - min(x_history)

                    direction_changes = 0
                    previous_direction = 0
                    strong_moves = 0

                    for dx in dx_history:
                        if abs(dx) < 0.012:
                            continue

                        strong_moves += 1
                        current_direction = 1 if dx > 0 else -1

                        if previous_direction != 0 and current_direction != previous_direction:
                            direction_changes += 1

                        previous_direction = current_direction

                    wave_debug = f"x_range={x_range:.2f} dir_changes={direction_changes}"

                    if x_range > 0.10 and direction_changes >= 2 and strong_moves >= 3:
                        waving_detected = True
                        gesture_text = "Waving"

                        if (now - last_trigger_time) >= trigger_cooldown:
                            current_mode = "EMERGENCY"
                            trigger_emergency_alert()
                            last_trigger_time = time.time()

                            x_history.clear()
                            dx_history.clear()

            else:
                hand_missing_frames += 1
                open_palm_start_time = None

                if hand_missing_frames >= 3:
                    x_history.clear()
                    dx_history.clear()

            # =================================================
            # IDLE RESET
            # =================================================
            if not hand_found and (time.time() - last_trigger_time) >= trigger_cooldown:
                current_mode = "IDLE"
                all_outputs_off()

            # =================================================
            # FPS
            # =================================================
            current_time = time.time()
            dt = current_time - prev_time
            if dt > 0:
                fps = 1.0 / dt
            prev_time = current_time

            status = "TRACKING" if hand_found else "NO HAND"

            # =================================================
            # ON SCREEN DISPLAY
            # =================================================
            cv2.putText(
                frame,
                f"Hand: {hand_label}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 255),
                2
            )

            cv2.putText(
                frame,
                f"Count: {raw_count}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2
            )

            cv2.putText(
                frame,
                f"Status: {status}",
                (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 200, 0),
                2
            )

            cv2.putText(
                frame,
                f"Mode: {current_mode}",
                (10, 120),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )

            cv2.putText(
                frame,
                f"Gesture: {gesture_text}",
                (10, 150),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (200, 200, 255),
                2
            )

            cv2.putText(
                frame,
                f"States: {finger_states}",
                (10, 180),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (180, 255, 180),
                2
            )

            cv2.putText(
                frame,
                f"Open Palm Hold: {open_palm_progress:.1f}s",
                (10, 210),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (255, 220, 180),
                2
            )

            cv2.putText(
                frame,
                f"Waving: {waving_detected}",
                (10, 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (180, 220, 255),
                2
            )

            cv2.putText(
                frame,
                wave_debug,
                (10, 270),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 180, 180),
                2
            )

            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (10, 300),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (180, 255, 180),
                2
            )

            cv2.putText(
                frame,
                "Q = quit",
                (10, 460),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (180, 180, 180),
                2
            )

            cv2.imshow("Touchless Help System", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

    finally:
        all_outputs_off()
        cap.release()
        cv2.destroyAllWindows()