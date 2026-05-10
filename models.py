from dataclasses import dataclass
from utils import sanitize_filename

import re

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
    queued: bool = False
    spinner_frame: int = 0
    parts: list[str] = None # List of ASINs for multi-part books

    def __post_init__(self):
        if self.parts is None:
            self.parts = []
        
        # Pre-calculate fields for faster sorting/filtering
        self._search_text = f"{self.asin} {self.author} {self.title} {self.narrator} {self.series_title} {self.year}".lower()
        
        # Extract numeric sequence for sorting
        try:
            match = re.search(r'(\d+\.?\d*)', self.series_sequence)
            self._series_seq_num = float(match.group(1)) if match else 0.0
        except (ValueError, IndexError):
            self._series_seq_num = 0.0

    @property
    def safe_title(self) -> str:
        return sanitize_filename(self.title)
