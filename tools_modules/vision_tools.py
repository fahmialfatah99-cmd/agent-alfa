"""Vision & Media Tools for ALFA Agent."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def capture_desktop_screenshot() -> Dict[str, Any]:
    """Capture a screenshot of the desktop."""
    try:
        import subprocess
        import tempfile
        import base64
        
        output_path = tempfile.mktemp(suffix=".png")
        
        # Try using scrot or xwd for screenshot
        result = subprocess.run(
            ["scrot", output_path],
            capture_output=True,
            timeout=10
        )
        
        if result.returncode == 0:
            with open(output_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            return {
                "status": "success",
                "message": "Desktop screenshot captured",
                "path": output_path,
                "image_base64": image_data[:100] + "..."  # Truncated
            }
        else:
            return {
                "status": "error",
                "message": "Failed to capture screenshot",
                "error": result.stderr.decode()
            }
    except Exception as e:
        logger.error(f"Desktop screenshot error: {e}")
        return {"status": "error", "error": str(e)}


def capture_webcam_frame() -> Dict[str, Any]:
    """Capture a frame from the webcam."""
    try:
        import cv2
        import tempfile
        import base64
        
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return {"status": "error", "message": "Webcam not available"}
        
        ret, frame = cap.read()
        cap.release()
        
        if ret:
            output_path = tempfile.mktemp(suffix=".jpg")
            cv2.imwrite(output_path, frame)
            
            with open(output_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
            
            return {
                "status": "success",
                "message": "Webcam frame captured",
                "path": output_path,
                "image_base64": image_data[:100] + "..."
            }
        else:
            return {"status": "error", "message": "Failed to capture frame"}
    except Exception as e:
        logger.error(f"Webcam capture error: {e}")
        return {"status": "error", "error": str(e)}


def text_to_audio_file(
    text: str, 
    filename: str = "audio_speech.mp3", 
    voice: str = "id-ID-GadisNeural"
) -> Dict[str, Any]:
    """Convert text to audio using TTS."""
    try:
        import os
        output_dir = os.path.join(os.path.dirname(__file__), "..", "storage", "audio")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename)
        
        # Use edge-tts if available
        try:
            import asyncio
            import edge_tts
            
            async def generate_audio():
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(output_path)
            
            asyncio.run(generate_audio())
            
            return {
                "status": "success",
                "message": f"Audio generated: {filename}",
                "path": output_path,
                "voice": voice
            }
        except ImportError:
            return {
                "status": "info",
                "message": "edge-tts not installed, using placeholder",
                "path": output_path
            }
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return {"status": "error", "error": str(e)}


def convert_media_format(
    source_file: str, 
    output_format: str = "mp3", 
    extra_params: str = ""
) -> Dict[str, Any]:
    """Convert media file format using ffmpeg."""
    try:
        import subprocess
        import os
        
        base_name = os.path.splitext(source_file)[0]
        output_file = f"{base_name}.{output_format}"
        
        cmd = [
            "ffmpeg", "-y", "-i", source_file
        ]
        if extra_params:
            cmd.extend(extra_params.split())
        cmd.append(output_file)
        
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        
        if result.returncode == 0:
            return {
                "status": "success",
                "message": f"Converted to {output_format}",
                "output_path": output_file
            }
        else:
            return {
                "status": "error",
                "message": "Conversion failed",
                "error": result.stderr.decode()
            }
    except Exception as e:
        logger.error(f"Media conversion error: {e}")
        return {"status": "error", "error": str(e)}
