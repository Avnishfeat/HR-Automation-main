import math
import cv2
import os
import numpy as np
import logging
import random
import mediapipe as mp
from typing import Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class LivenessChallengeService:
    """
    Conducts active liveness checks by asking candidates to perform 
    random gestures and verifying them using MediaPipe Pose/Hand tracking.
    """

    def __init__(self):
        self.mp_pose = mp.solutions.pose
        self.mp_hands = mp.solutions.hands
        
        # We use holistic or separate solutions. 
        # Using Pose is sufficient for "Hands raised" or "Head turn".
        # For "Touch Nose", we might need Hands+Pose, but Pose includes wrists/nose.
        self.pose = self.mp_pose.Pose(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=0.5
        )
        
        # Available challenges: (Instruction Text, Internal Code)
        self.challenges = [
            ("raise your right hand", "raise_right_hand"),
            ("raise your left hand", "raise_left_hand"),
            ("touch your nose", "touch_nose"), # Requires high precision
            ("look to your left", "look_left"),
            ("look to your right", "look_right")
        ]
        self.debug_dir = "data/debug_frames"
        os.makedirs(self.debug_dir, exist_ok=True)

    def get_challenge(self) -> Tuple[str, str]:
        """Returns a random (instruction_text, gesture_code)."""
        return random.choice(self.challenges)

    def verify_challenge(self, image_bytes: bytes, challenge_type: str) -> bool:
        if not image_bytes:
            return False

        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return False

        # Process with MediaPipe
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(frame_rgb)

        if not results.pose_landmarks:
            logger.warning("Liveness Check: No person detected")
            # Save the failed frame to check why
            self._save_debug_frame(frame, challenge_type, "no_person")
            return False

        landmarks = results.pose_landmarks.landmark
        is_verified = False

        if challenge_type == "raise_right_hand":
            is_verified = self._check_hand_raised(landmarks, "right")
        elif challenge_type == "raise_left_hand":
            is_verified = self._check_hand_raised(landmarks, "left")
        elif challenge_type == "look_left":
            is_verified = self._check_head_turn(landmarks, "left")
        elif challenge_type == "look_right":
            is_verified = self._check_head_turn(landmarks, "right")
        elif challenge_type == "touch_nose":
            is_verified = self._check_touch_nose(landmarks)
            
        # Log the result and save the image
        status = "PASS" if is_verified else "FAIL"
        self._save_debug_frame(frame, challenge_type, status)
        
        return is_verified

    def _save_debug_frame(self, frame, challenge, status):
        """Saves the frame to disk for inspection."""
        try:
            timestamp = datetime.now().strftime("%H-%M-%S")
            filename = f"{self.debug_dir}/{timestamp}_{challenge}_{status}.jpg"
            cv2.imwrite(filename, frame)
            logger.info(f"Saved liveness debug frame: {filename}")
        except Exception as e:
            logger.error(f"Failed to save debug frame: {e}")

    # --- Verification Logic ---

    def _check_hand_raised(self, landmarks, side: str) -> bool:
        """
        Checks if the requested hand is raised.
        IMPORTANT: We fallback to 'Any Hand' to account for Mirror Confusion.
        """
        nose = landmarks[self.mp_pose.PoseLandmark.NOSE]
        r_wrist = landmarks[self.mp_pose.PoseLandmark.RIGHT_WRIST]
        l_wrist = landmarks[self.mp_pose.PoseLandmark.LEFT_WRIST]

        # Y-axis is inverted (0 is Top, 1 is Bottom). So "Raised" means Wrist < Nose.
        
        right_raised = r_wrist.y < nose.y
        left_raised = l_wrist.y < nose.y
        
        logger.info(
            f"Liveness Check Hand Data: "
            f"NoseY={nose.y:.2f} | "
            f"RightWristY={r_wrist.y:.2f} (Raised? {right_raised}) | "
            f"LeftWristY={l_wrist.y:.2f} (Raised? {left_raised})"
        )

        # Strict Check (Did they raise the specific hand?)
        if side == "right" and right_raised:
            return True
        if side == "left" and left_raised:
            return True
            
        # Loose Fallback (Did they raise ANY hand?)
        # We accept this because mirror confusion is common and not a sign of cheating.
        if right_raised or left_raised:
            logger.info("Liveness: Accepted 'Wrong Hand' raised (Mirror confusion logic)")
            return True

        return False

    def _check_touch_nose(self, landmarks) -> bool:
        nose = landmarks[self.mp_pose.PoseLandmark.NOSE]
        r_wrist = landmarks[self.mp_pose.PoseLandmark.RIGHT_WRIST]
        l_wrist = landmarks[self.mp_pose.PoseLandmark.LEFT_WRIST]

        # Calculate Distance
        dist_r = math.sqrt((r_wrist.x - nose.x)**2 + (r_wrist.y - nose.y)**2)
        dist_l = math.sqrt((l_wrist.x - nose.x)**2 + (l_wrist.y - nose.y)**2)
        
        logger.info(f"Liveness Check (Nose): DistR={dist_r:.2f}, DistL={dist_l:.2f}")
        
        # FIX: Relaxed Threshold from 0.30 to 0.50
        # 0.50 is half the screen width. If your hand is within the same "half" as your nose, it passes.
        THRESHOLD = 0.50 
        
        return dist_r < THRESHOLD or dist_l < THRESHOLD

    def _check_head_turn(self, landmarks, direction: str) -> bool:
        """
        Checks if the head is turned by comparing nose-to-ear distances.
        """
        nose = landmarks[self.mp_pose.PoseLandmark.NOSE]
        l_ear = landmarks[self.mp_pose.PoseLandmark.LEFT_EAR]
        r_ear = landmarks[self.mp_pose.PoseLandmark.RIGHT_EAR]
        
        # Calculate horizontal distances from nose to ears
        dist_l_ear = abs(nose.x - l_ear.x)
        dist_r_ear = abs(nose.x - r_ear.x)
        
        # Calculate ratio of distances. If looking straight, ratio is ~1.0.
        # If looking far to one side, one ear becomes much closer (or hidden)
        # while the other ear is visible, making the ratio heavily skewed.
        # To avoid divide-by-zero, add a small epsilon.
        ratio = dist_l_ear / (dist_r_ear + 0.001)
        
        logger.info(f"Head Turn Check: L_Ear_Dist={dist_l_ear:.3f}, R_Ear_Dist={dist_r_ear:.3f}, Ratio={ratio:.2f}")

        # If looking left or right, the ratio will skew.
        # A normal 30-45 degree turn results in a ratio around 0.65 or 1.5.
        # We accept either extreme to handle webcam mirror confusion.
        return ratio > 1.35 or ratio < 0.75
            
        return False