from dataclasses import dataclass
from utils import sanitize_filename

@dataclass
class Audiobook:
    asin: str
    author: str
    title: str
    status: str = ""
    working: bool = False
    queued: bool = False
    spinner_frame: int = 0

    @property
    def safe_title(self) -> str:
        return sanitize_filename(self.title)
