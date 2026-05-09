from dataclasses import dataclass
from utils import sanitize_filename

@dataclass
class Audiobook:
    asin: str
    author: str
    title: str
    narrator: str = ""
    year: str = ""
    duration_ms: int = 0
    series_title: str = ""
    series_sequence: str = ""
    status: str = ""
    working_mode: str = "" # "", "downloading", "processing", "queued"
    working: bool = False
    queued: bool = False
    spinner_frame: int = 0

    @property
    def safe_title(self) -> str:
        return sanitize_filename(self.title)
