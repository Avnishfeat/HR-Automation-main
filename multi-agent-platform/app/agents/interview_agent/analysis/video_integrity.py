
# app/services/interview/analysis/video_integrity.py
import cv2
import numpy as np
import logging
from typing import Literal, Tuple

logger = logging.getLogger(__name__)

# Lazy load MediaPipe to avoid import errors if not installed
_mp_face_detection = None
_mp_drawing = None

def _get_mediapipe():
    """Lazy load MediaPipe Face Detection module."""
    global _mp_face_detection, _mp_drawing
    if _mp_face_detection is None:
        try:
            import mediapipe as mp
            # Check if 'solutions' attribute exists (older API)
            if hasattr(mp, 'solutions'):
                _mp_face_detection = mp.solutions.face_detection
                _mp_drawing = mp.solutions.drawing_utils
                logger.info("MediaPipe Face Detection loaded successfully (solutions API)")
            else:
                # New API (0.10.18+) removed solutions, face detection needs Tasks API
                logger.warning("MediaPipe 'solutions' API not available. Face detection disabled (upgrade code to Tasks API for full support).")
        except ImportError:
            logger.warning("MediaPipe not installed. Face detection disabled.")
        except Exception as e:
            logger.warning(f"MediaPipe initialization failed: {e}. Face detection disabled.")
    return _mp_face_detection

class VideoIntegrityAnalyzer:
    def __init__(self):
        # Frozen Check
        self.prev_frame_gray = None
        self.consecutive_static_frames = 0
        self.FROZEN_THRESHOLD_MSE = 0.5 
        self.STATIC_FRAME_LIMIT = 4

        # Motion Check (ORB)
        self.orb = cv2.ORB_create(nfeatures=400)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.prev_keypoints = None
        self.prev_descriptors = None
        
        # Thresholds (Very relaxed to avoid false positives during normal interview)
        # Only trigger for very significant movements like standing up or picking up camera
        self.CAMERA_MOTION_THRESHOLD = 100.0  # Pixels (Median) - Global Shift (was 50)
        self.PERSON_MOTION_THRESHOLD = 200.0  # Pixels (90th Percentile) - Local Shift (was 100)
        
        self.consecutive_motion_frames = 0
        self.MOTION_FRAME_LIMIT = 5  # Require 5 consecutive frames before triggering (was 3)

        # Face Detection (MediaPipe)
        self.face_detector = None
        self.FACE_DETECTION_CONFIDENCE = 0.7  # Increased from 0.5 for fewer false positives
        self.MIN_FACE_SIZE_RATIO = 0.03  # Minimum face size as ratio of frame (ignore tiny distant faces)
        self._init_face_detector()
        
        # Background person detection tracking (with consecutive frame requirement)
        self.background_person_count = 0
        self.consecutive_multiple_face_frames = 0
        self.MULTIPLE_FACE_FRAME_LIMIT = 3  # Require 3 consecutive frames with multiple faces

    def _init_face_detector(self):
        """Initialize MediaPipe face detector."""
        mp_face = _get_mediapipe()
        if mp_face:
            try:
                self.face_detector = mp_face.FaceDetection(
                    model_selection=0,  # 0 = short range (within 2m), 1 = full range
                    min_detection_confidence=self.FACE_DETECTION_CONFIDENCE
                )
                logger.info("Face detector initialized")
            except Exception as e:
                logger.error(f"Failed to initialize face detector: {e}")
                self.face_detector = None

    def check_frame(self, image_bytes: bytes) -> str:
        """
        Analyzes a frame for integrity issues.
        
        Returns:
            - "ok": No issues
            - "frozen": Video feed is frozen
            - "camera_moving": Excessive camera/person motion
            - "multiple_faces": More than one face detected
            - "error": Analysis failed
        """
        if not image_bytes: return "error"

        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None: return "error"

            # 1. RESIZE to standard analysis size (Prevents crash)
            frame = cv2.resize(frame, (640, 480))
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            status = "ok"

            # 2. FROZEN CHECK
            if self.prev_frame_gray is not None:
                diff = gray.astype("float") - self.prev_frame_gray.astype("float")
                mse = np.mean(diff ** 2)
                
                if mse < self.FROZEN_THRESHOLD_MSE:
                    self.consecutive_static_frames += 1
                else:
                    self.consecutive_static_frames = 0
                    
                if self.consecutive_static_frames > self.STATIC_FRAME_LIMIT:
                    return "frozen"

            # 3. MOTION DETECTION (Global & Local)
            motion_type = self._analyze_motion_type(gray)
            
            if motion_type in ["camera_moving", "person_moving"]:
                self.consecutive_motion_frames += 1
                if self.consecutive_motion_frames >= self.MOTION_FRAME_LIMIT:
                    status = "camera_moving"
            else:
                self.consecutive_motion_frames = 0

            # 4. FACE DETECTION - Check for multiple faces (background person)
            face_count = self._count_faces(frame)
            if face_count > 1:
                self.consecutive_multiple_face_frames += 1
                # Only count as background person after consecutive frames (reduces false positives)
                if self.consecutive_multiple_face_frames >= self.MULTIPLE_FACE_FRAME_LIMIT:
                    self.background_person_count += 1
                    logger.warning(f"Multiple faces confirmed: {face_count} faces ({self.consecutive_multiple_face_frames} consecutive frames)")
                    self.consecutive_multiple_face_frames = 0  # Reset after counting
                    self.prev_frame_gray = gray
                    return "multiple_faces"
            else:
                self.consecutive_multiple_face_frames = 0

            self.prev_frame_gray = gray
            return status

        except Exception as e:
            logger.error(f"Integrity check failed: {e}")
            return "error"

    def _count_faces(self, frame: np.ndarray) -> int:
        """
        Count the number of significant faces in a frame using MediaPipe.
        Filters out small/distant faces to reduce false positives.
        """
        if self.face_detector is None:
            return 0
        
        try:
            # MediaPipe expects RGB
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.face_detector.process(rgb_frame)
            
            if not results.detections:
                return 0
            
            # Filter by face size - ignore small/distant faces
            frame_height, frame_width = frame.shape[:2]
            min_face_area = frame_width * frame_height * self.MIN_FACE_SIZE_RATIO
            
            significant_faces = 0
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                face_width = bbox.width * frame_width
                face_height = bbox.height * frame_height
                face_area = face_width * face_height
                
                # Only count if face is large enough (not a poster, photo, or distant person)
                if face_area >= min_face_area:
                    significant_faces += 1
            
            return significant_faces
            
        except Exception as e:
            logger.debug(f"Face detection failed: {e}")
            return 0

    def get_background_person_count(self) -> int:
        """Returns the total count of frames where multiple faces were detected."""
        return self.background_person_count

    def reset_background_count(self):
        """Resets the background person detection counter."""
        self.background_person_count = 0

    def _analyze_motion_type(self, gray_frame) -> str:
        kp, des = self.orb.detectAndCompute(gray_frame, None)

        if self.prev_descriptors is None or des is None or len(des) < 10:
            self.prev_keypoints = kp
            self.prev_descriptors = des
            return "ok"

        matches = self.bf.match(self.prev_descriptors, des)
        matches = sorted(matches, key=lambda x: x.distance)
        num_good_matches = int(len(matches) * 0.5)
        good_matches = matches[:num_good_matches]

        if len(good_matches) < 5:
            self.prev_keypoints = kp
            self.prev_descriptors = des
            return "ok"

        # Calculate displacements
        pts_prev = np.float32([self.prev_keypoints[m.queryIdx].pt for m in good_matches])
        pts_curr = np.float32([kp[m.trainIdx].pt for m in good_matches])
        distances = np.linalg.norm(pts_curr - pts_prev, axis=1)
        
        # Metric 1: Median (Background/Global Motion)
        median_motion = np.median(distances)
        
        # Metric 2: Peak (90th Percentile) (Person/Local Motion)
        peak_motion = np.percentile(distances, 90)

        self.prev_keypoints = kp
        self.prev_descriptors = des

        # Case A: Camera is moving (Everything shifts)
        if median_motion > self.CAMERA_MOTION_THRESHOLD:
            logger.warning(f"Global Motion: {median_motion:.2f}px")
            return "camera_moving"
        
        # Case B: Person is moving (Background stable, Outliers high)
        if peak_motion > self.PERSON_MOTION_THRESHOLD:
            logger.warning(f"Local Motion Detected: {peak_motion:.2f}px (Median: {median_motion:.2f}px)")
            return "person_moving"
        
        return "ok"
