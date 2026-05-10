class AudiobookError(Exception):
    """Base exception for all audiobook-related errors."""
    pass

class AudibleAPIError(AudiobookError):
    """Raised when an Audible API call fails."""
    pass

class ConversionError(AudiobookError):
    """Raised when an FFmpeg conversion fails."""
    pass

class DependencyError(AudiobookError):
    """Raised when a required system dependency (ffmpeg, audible-cli) is missing."""
    pass

class AuthenticationError(AudiobookError):
    """Raised when the user is not authenticated with audible-cli."""
    pass

class DownloadError(AudiobookError):
    """Raised when an audiobook download fails."""
    pass
