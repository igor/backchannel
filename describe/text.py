"""Apple Vision OCR boundary. This is the only production module importing Vision."""
from pathlib import Path


class VisionUnavailableError(RuntimeError):
    pass


def _configure_request(request) -> None:
    request.setRecognitionLevel_(0)


def recognize(image_path: Path) -> list[tuple[str, float]]:
    try:
        from Foundation import NSURL
        from Vision import VNImageRequestHandler, VNRecognizeTextRequest
    except ImportError as exc:
        raise VisionUnavailableError("pyobjc-framework-Vision is unavailable") from exc
    request = VNRecognizeTextRequest.alloc().init()
    _configure_request(request)
    handler = VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(str(Path(image_path))), None
    )
    _success, error = handler.performRequests_error_([request], None)
    if error is not None:
        raise RuntimeError(str(error))
    rows = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1) or []
        if candidates:
            candidate = candidates[0]
            rows.append((str(candidate.string()), float(candidate.confidence())))
    return rows
