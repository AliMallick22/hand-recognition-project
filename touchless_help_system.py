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
EMAIL_ENABLED = False

SENDER_EMAIL = "your_email@gmail.com"
SENDER_PASSWORD = "your_app_password"
RECEIVER_EMAIL = "caregiver_email@gmail.com"

def send_caregiver_email():
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
    green_led.off()
    red_led.off()
    white_led.off()
    buzzer.stop()

def caregiver_jingle():
    notes = ["C5", "E5", "G5", "E5", "C5"]
    lengths = [0.16, 0.16, 0.22, 0.16, 0.22]

    for note, length in zip(notes, lengths):
        buzzer.play(Tone(note))
        time.sleep(length)
        buzzer.stop()
        time.sleep(0.04)

def emergency_alarm(duration=3.0):
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
    buzzer.play(Tone("C5"))
    time.sleep(0.08)
    buzzer.stop()

def trigger_caregiver_alert():
    all_outputs_off()
    green_led.on()
    print("Caregiver notified")
    caregiver_jingle()
    send_caregiver_email()

def trigger_emergency_alert():
    all_outputs_off()
    red_led.on()
    print("Emergency alert activated")
    emergency_alarm(duration=3.0)

def trigger_lights_on():
    all_outputs_off()
    white_led.on()
    print("Lights on")
    light_confirmation_tone()

# =========================================================
# STARTUP TEST
# =========================================================
def startup_test():
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
    landmarks = hand_landmarks.landmark
    finger_states = []

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
    return finger_states == [1, 1, 1, 1, 1]

def is_two_fingers(finger_states):
    return finger_states == [0, 1, 1, 0, 0]

def get_hand_center(hand_landmarks):
    landmarks = hand_landmarks.landmark
    x = (landmarks[0].x + landmarks[9].x) / 2.0
    y = (landmarks[0].y + landmarks[9].y) / 2.0
    return x, y

def is_wave_ready(finger_states):
    return sum(finger_states) >= 4

# =========================================================
# STATE VARIABLES
# =========================================================
open_palm_start_time = None
current_mode = "IDLE"

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