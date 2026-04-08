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
EMAIL_ENABLED = True

SENDER_EMAIL = "abczrpp@gmail.com"
SENDER_PASSWORD = "rnvp dqsf rmrj vkgh"
RECEIVER_EMAIL = "2008alimallick@gmail.com"

def send_caregiver_email():
    # I made this its own function so the main loop stays cleaner
    # and I can just call it when the open palm gesture is held long enough.
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
# OUTPUT STATE
# =========================================================
# This section is important because I do NOT want the white LED
# to turn off just because my hand disappears from the camera.
# So I store the light state in a variable and keep refreshing it.

lights_on = False
green_until = 0.0
red_until = 0.0
status_text = "IDLE"
status_until = 0.0

def set_status(text, duration=2.0):
    # This just changes the on-screen mode text for a short time.
    global status_text, status_until
    status_text = text
    status_until = time.time() + duration

def get_display_mode():
    # If a temporary status is active, show it.
    # Otherwise just show LIGHTS ON or IDLE based on the saved state.
    now = time.time()
    if now < status_until:
        return status_text
    return "LIGHTS ON" if lights_on else "IDLE"

def all_outputs_off():
    # This fully shuts everything off.
    # I only really want this during startup/reset/quit,
    # not every time the hand disappears.
    green_led.off()
    red_led.off()
    white_led.off()
    buzzer.stop()

def refresh_outputs():
    # This runs every loop and updates the real hardware
    # based on the saved states above.
    # The big idea is:
    # white LED depends on lights_on
    # green LED depends on green_until
    # red LED depends on red_until

    now = time.time()

    if lights_on:
        white_led.on()
    else:
        white_led.off()

    if now < green_until:
        green_led.on()
    else:
        green_led.off()

    if now < red_until:
        red_led.on()
    else:
        red_led.off()

# =========================================================
# SOUND HELPERS
# =========================================================
def caregiver_jingle():
    # Just a little melody for caregiver notification
    notes = ["C5", "E5", "G5", "E5", "C5"]
    lengths = [0.16, 0.16, 0.22, 0.16, 0.22]

    for note, length in zip(notes, lengths):
        buzzer.play(Tone(note))
        time.sleep(length)
        buzzer.stop()
        time.sleep(0.04)

def emergency_alarm(duration=3.0):
    # Louder / more urgent sound pattern for emergency
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

def light_on_tone():
    buzzer.play(Tone("C5"))
    time.sleep(0.08)
    buzzer.stop()

def light_off_tone():
    buzzer.play(Tone("A4"))
    time.sleep(0.08)
    buzzer.stop()

# =========================================================
# ACTION TRIGGERS
# =========================================================
def trigger_caregiver_alert():
    global green_until

    # Instead of turning everything on/off directly in random places,
    # I store how long the green LED should stay on.
    green_until = time.time() + 3.0
    set_status("CAREGIVER ALERT", 3.0)

    print("Caregiver notified")
    caregiver_jingle()
    send_caregiver_email()

def trigger_emergency_alert():
    global red_until

    red_until = time.time() + 4.0
    set_status("EMERGENCY ALERT", 4.0)

    print("Emergency alert activated")
    emergency_alarm(duration=3.0)

def trigger_lights_on():
    global lights_on

    # This is the main change for the light feature.
    # I set lights_on = True and leave it like that,
    # so the light stays on even after I move my hand away.
    lights_on = True
    set_status("LIGHTS ON", 2.0)

    print("Lights on")
    light_on_tone()

def trigger_lights_off():
    global lights_on

    # Same idea here, I save OFF as the new light state.
    lights_on = False
    set_status("LIGHTS OFF", 2.0)

    print("Lights off")
    light_off_tone()

# =========================================================
# STARTUP TEST
# =========================================================
def startup_test():
    # Just a quick check at startup so I know the LEDs and buzzer work.
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

    # Thumb is annoying because it points sideways more than upward.
    # So for thumb I compare x positions instead of y positions.
    # Also MediaPipe labels the hand as Right or Left,
    # so I have to flip the thumb logic depending on the hand.
    if hand_label == "Right":
        thumb_up = 1 if landmarks[4].x < landmarks[3].x else 0
    else:
        thumb_up = 1 if landmarks[4].x > landmarks[3].x else 0

    finger_states.append(thumb_up)

    # These are the fingertip landmark numbers for:
    # index, middle, ring, pinky
    finger_tips = [8, 12, 16, 20]

    # These are the PIP joints for those fingers.
    # I compare tip vs joint to decide whether the finger is up.
    finger_pips = [6, 10, 14, 18]

    for tip, pip in zip(finger_tips, finger_pips):
        # In image coordinates, smaller y means higher on screen.
        # So if the tip is above the joint, I count that finger as up.
        is_up = 1 if landmarks[tip].y < landmarks[pip].y else 0
        finger_states.append(is_up)

    raw_count = sum(finger_states)
    return raw_count, finger_states

def is_open_palm(finger_states):
    # All 5 fingers up
    return finger_states == [1, 1, 1, 1, 1]

def is_two_fingers(finger_states):
    # Index + middle only
    return finger_states == [0, 1, 1, 0, 0]

def is_one_finger(finger_states):
    # Index finger only
    return finger_states == [0, 1, 0, 0, 0]

def get_hand_center(hand_landmarks):
    # I use a rough hand center for wave tracking.
    # landmark 0 is wrist, landmark 9 is around the middle of the palm.
    # Averaging them gives me a decent center point.
    landmarks = hand_landmarks.landmark
    x = (landmarks[0].x + landmarks[9].x) / 2.0
    y = (landmarks[0].y + landmarks[9].y) / 2.0
    return x, y

def is_wave_ready(finger_states):
    # I only allow wave detection when the hand looks open enough.
    # This helps stop random closed-hand movement from triggering emergency.
    return sum(finger_states) >= 4

# =========================================================
# STATE VARIABLES
# =========================================================
open_palm_start_time = None

# These deques store recent x positions of the hand,
# and also the changes in x from frame to frame.
# I use them to figure out whether the hand is actually waving left and right.
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

            # flip makes the camera feel mirror-like, which is easier to use
            frame = cv2.flip(frame, 1)
            frame = cv2.resize(frame, (640, 480))

            # OpenCV uses BGR, MediaPipe wants RGB
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

                # This draws the landmark dots and finger connections on the screen
                mp_drawing.draw_landmarks(
                    frame,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS
                )

                raw_count, finger_states = count_fingers(hand_landmarks, hand_label)

                center_x, center_y = get_hand_center(hand_landmarks)

                # I store how much the hand moved horizontally since the last frame.
                # This matters for the wave gesture.
                if len(x_history) > 0:
                    dx = center_x - x_history[-1]
                    dx_history.append(dx)

                x_history.append(center_x)

                # -------------------------------------------------
                # OPEN PALM, hold 3 seconds for caregiver email
                # -------------------------------------------------
                if is_open_palm(finger_states):
                    gesture_text = "Open Palm"

                    # First frame where open palm starts
                    if open_palm_start_time is None:
                        open_palm_start_time = now

                    # Keep measuring how long the palm stays open
                    open_palm_progress = now - open_palm_start_time

                    # Only trigger after 3 full seconds and cooldown passed
                    if open_palm_progress >= 3.0 and (now - last_trigger_time) >= trigger_cooldown:
                        trigger_caregiver_alert()
                        last_trigger_time = time.time()

                else:
                    # If I stop showing open palm, reset the timer
                    open_palm_start_time = None

                # -------------------------------------------------
                # TWO FINGERS, lights on
                # -------------------------------------------------
                if is_two_fingers(finger_states):
                    gesture_text = "Two Fingers"

                    # not lights_on check stops the sound from repeating
                    # when the light is already on
                    if (now - last_trigger_time) >= trigger_cooldown and not lights_on:
                        trigger_lights_on()
                        last_trigger_time = time.time()

                # -------------------------------------------------
                # ONE FINGER, lights off
                # -------------------------------------------------
                elif is_one_finger(finger_states):
                    gesture_text = "One Finger"

                    if (now - last_trigger_time) >= trigger_cooldown and lights_on:
                        trigger_lights_off()
                        last_trigger_time = time.time()

                # -------------------------------------------------
                # WAVING, emergency
                # -------------------------------------------------
                # The wave is more complicated than simple finger counting.
                # I do not just look at the current frame.
                # I look at recent hand movement across multiple frames.
                if len(x_history) >= 6 and len(dx_history) >= 5 and is_wave_ready(finger_states):
                    x_range = max(x_history) - min(x_history)

                    direction_changes = 0
                    previous_direction = 0
                    strong_moves = 0

                    for dx in dx_history:
                        # Tiny wiggles should not count as a wave
                        if abs(dx) < 0.012:
                            continue

                        strong_moves += 1
                        current_direction = 1 if dx > 0 else -1

                        # Count how many times the hand changes horizontal direction
                        # Example: left -> right -> left
                        if previous_direction != 0 and current_direction != previous_direction:
                            direction_changes += 1

                        previous_direction = current_direction

                    wave_debug = f"x_range={x_range:.2f} dir_changes={direction_changes}"

                    # I only call it a real wave if:
                    # 1. the hand moved enough side to side
                    # 2. it changed direction enough times
                    # 3. there were enough strong moves
                    if x_range > 0.10 and direction_changes >= 2 and strong_moves >= 3:
                        waving_detected = True
                        gesture_text = "Waving"

                        if (now - last_trigger_time) >= trigger_cooldown:
                            trigger_emergency_alert()
                            last_trigger_time = time.time()

                            # Clear the motion history so it does not instantly trigger again
                            x_history.clear()
                            dx_history.clear()

            else:
                hand_missing_frames += 1
                open_palm_start_time = None

                # If the hand is gone for a few frames,
                # clear motion history so old movement does not affect new detection.
                if hand_missing_frames >= 3:
                    x_history.clear()
                    dx_history.clear()

            # This updates LEDs every loop using the saved state
            refresh_outputs()

            # FPS calculation
            current_time = time.time()
            dt = current_time - prev_time
            if dt > 0:
                fps = 1.0 / dt
            prev_time = current_time

            status = "TRACKING" if hand_found else "NO HAND"
            current_mode = get_display_mode()

            # =========================================================
            # ON-SCREEN TEXT
            # =========================================================
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
                f"Light State: {'ON' if lights_on else 'OFF'}",
                (10, 300),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 180),
                2
            )

            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (10, 330),
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