import subprocess
import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Callable
from models import Audiobook
from utils import sanitize_filename, convert_chapters_json_to_ffmetadata

class AudiobookService:
    def __init__(self, config: Dict):
        self.config = config

    @property
    def library_path(self) -> Path:
        return Path(self.config.get("library_path", str(Path.cwd())))

    @property
    def activation_bytes(self) -> str:
        """Returns sanitized activation bytes (8 hex chars, no 0x prefix)."""
        raw = self.config.get("activation_bytes", "").strip().lower()
        if raw.startswith("0x"):
            raw = raw[2:]
        # Remove any non-hex characters just in case
        return re.sub(r'[^0-9a-f]', '', raw)

    async def is_authenticated(self) -> bool:
        """Checks if audible-cli has an active/configured profile."""
        try:
            process = await asyncio.create_subprocess_exec(
                "audible", "manage", "profile", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            output = stdout.decode()
            # Check if there's a line with an asterisk (active profile)
            return "*" in output
        except Exception:
            return False

    def get_status(self, asin: str, title: str, file_set: Optional[set] = None) -> str:
        """Checks the filesystem for the status of a book."""
        safe_title = sanitize_filename(title)
        lib = self.library_path

        if file_set is not None:
            # Check for M4B
            if f"{safe_title}.m4b" in file_set or f"{asin}.m4b" in file_set:
                return "[bold green]✔[/]"
            
            # Check for AAX (approximate glob with startswith)
            for f in file_set:
                if f.startswith(asin) and f.endswith(".aax"):
                    return "[bold yellow]⬇[/]"
                if f.startswith(safe_title) and f.endswith(".aax"):
                    return "[bold yellow]⬇[/]"
            return ""

        # Fallback for M4B (sanitized title or ASIN)
        if (lib / f"{safe_title}.m4b").exists() or (lib / f"{asin}.m4b").exists():
            return "[bold green]✔[/]"

        # Fallback for AAX
        aax_patterns = [f"{asin}*.aax", f"{safe_title}*.aax"]
        for pattern in aax_patterns:
            if any(lib.glob(pattern)):
                return "[bold yellow]⬇[/]"

        return ""

    async def verify_file_exists(self, path: Path, timeout: float = 2.0) -> bool:
        """Polls for a file's existence for a limited time."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            if path.exists():
                return True
            await asyncio.sleep(0.1)
        return False

    async def fetch_library(self) -> List[Audiobook]:
        """Fetches the library using the Audible JSON API for robust data."""
        try:
            # We use product_desc for the title and series for series info
            cmd = [
                "audible", "api", "/1.0/library",
                "-p", "num_results=1000",
                "-p", "response_groups=product_details,product_desc,contributors,series"
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise RuntimeError(f"Audible API failed: {stderr.decode().strip()}")

            data = json.loads(stdout.decode())
            items = data.get("items", [])
            books = []
            
            # Pre-list directory for faster status checks
            lib = self.library_path
            file_set = {f.name for f in lib.iterdir()} if lib.exists() else set()

            for item in items:
                asin = item.get("asin", "")
                title = item.get("title") or "Unknown Title"
                
                # Extract authors
                authors_list = item.get("authors", [])
                author = ", ".join([a.get("name", "") for a in authors_list if a.get("name")])
                if not author:
                    author = "Unknown Author"
                
                # Extract narrators
                narrators_list = item.get("narrators", [])
                narrator = ", ".join([n.get("name", "") for n in narrators_list if n.get("name")])
                if not narrator:
                    narrator = "Unknown Narrator"

                # Extract year from date_first_available (e.g., "2021-10-19")
                year = ""
                date_str = item.get("date_first_available", "")
                if date_str and len(date_str) >= 4:
                    year = date_str[:4]

                # Extract duration
                duration_ms = 0
                runtime = item.get("runtime_length_min")
                if runtime:
                    duration_ms = int(runtime) * 60 * 1000

                # Extract series
                series_list = item.get("series", [])
                series_title = ""
                series_sequence = ""
                if series_list:
                    series_title = series_list[0].get("title", "")
                    series_sequence = series_list[0].get("sequence", "")

                status = self.get_status(asin, title, file_set=file_set)
                
                books.append(Audiobook(
                    asin=asin,
                    author=author,
                    title=title,
                    narrator=narrator,
                    year=year,
                    duration_ms=duration_ms,
                    series_title=series_title,
                    series_sequence=series_sequence,
                    status=status
                ))
                    
            return books
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Unexpected error fetching library: {e}") from e

    async def download(self, asin: str, log_callback: Callable[[str], None]) -> int:
        """Runs the audible download command asynchronously."""
        cmd = ["audible", "download", "-a", asin, "--aax", "--cover", "--chapter", "--filename-mode", "asin_ascii", "-y"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(self.library_path)
        )

        if process.stdout:
            buffer = ""
            while True:
                chunk_bytes = await process.stdout.read(4096)
                if not chunk_bytes:
                    break
                
                buffer += chunk_bytes.decode(errors="ignore")
                if "\r" in buffer or "\n" in buffer:
                    lines = re.split(r'[\r\n]', buffer)
                    buffer = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if line:
                            try:
                                log_callback(line)
                            except Exception:
                                pass
        
        return await process.wait()

    async def process_m4b(self, book: Audiobook, log_callback: Callable[[str], None]) -> bool:
        """Converts AAX to M4B with chapters and cover art asynchronously."""
        if not self.activation_bytes:
            log_callback("[bold red]Activation bytes not set![/]")
            return False

        lib = self.library_path
        safe_title = book.safe_title
        
        # 1. Find Chapter JSON
        json_path = None
        for pattern in [f"{book.asin}*.json", f"{safe_title}*.json"]:
            matches = [m for m in lib.glob(pattern) if m.suffix == ".json"]
            if matches:
                json_path = matches[0]
                break
        if not json_path:
            log_callback("[bold red]Chapter JSON not found.[/]")
            return False

        # 2. Find AAX
        aax_path = None
        for pattern in [f"{book.asin}*.aax", f"{safe_title}*.aax"]:
            matches = list(lib.glob(pattern))
            if matches:
                aax_path = matches[0]
                break
        if not aax_path:
            log_callback("[bold red]AAX file not found.[/]")
            return False

        # 3. Find Cover
        cover_path = None
        for pattern in [f"{book.asin}*.jpg", f"{safe_title}*.jpg"]:
            matches = list(lib.glob(pattern))
            if matches:
                cover_path = matches[0]
                break

        meta_path = None
        # 4. Prepare Metadata
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
            
            # Calculate duration from chapters for accurate processing progress
            def get_total_duration(chapters):
                total = 0
                for c in chapters:
                    total += int(c.get('length_ms', 0))
                    if 'chapters' in c:
                        # Only top-level chapters for duration usually, but let's be safe
                        pass 
                return total
            
            # Sum up top-level chapters
            ch_list = json_data.get('content_metadata', {}).get('chapter_info', {}).get('chapters', [])
            book.duration_ms = sum(int(c.get('length_ms', 0)) for c in ch_list)

            # Prepare tags for cleaner metadata
            tags = {
                "title": book.title,
                "artist": book.author,
                "album": book.series_title if book.series_title else book.title,
                "genre": "Audiobook",
                "comment": f"ASIN: {book.asin}",
                "composer": book.narrator,
                "date": book.year
            }
            ffmetadata = convert_chapters_json_to_ffmetadata(json_data, tags=tags)
            
            # Use .ffmetadata suffix and explicit utf-8 encoding
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ffmetadata', delete=False, encoding='utf-8') as tmp_meta:
                tmp_meta.write('\n'.join(ffmetadata))
                tmp_meta.write('\n') # Ensure trailing newline
                meta_path = Path(tmp_meta.name)
            log_callback(f"Prepared metadata: {meta_path.name}")
        except Exception as e:
            log_callback(f"[bold red]Metadata error: {e}[/]")
            return False

        try:
            # 5. Build FFmpeg command
            output_path = lib / f"{book.asin}.m4b"
            # -activation_bytes is an input option for aax, placed before -i
            # We remove forced -f aax as auto-detection is usually more robust
            cmd = ["ffmpeg", "-y", "-activation_bytes", self.activation_bytes, "-i", str(aax_path), "-f", "ffmetadata", "-i", str(meta_path)]
            
            if cover_path:
                cmd.extend(["-i", str(cover_path)])
                # Map audio from 0, metadata from 1, cover from 2
                # -map_metadata -1 strips all metadata first
                # -map_metadata 1 then applies our clean metadata file
                cmd.extend([
                    "-map", "0:a", "-map", "2:v", 
                    "-map_metadata", "-1", "-map_metadata", "1", 
                    "-map_chapters", "1",
                    "-c:a", "copy", "-c:v", "copy", 
                    "-disposition:v:0", "attached_pic"
                ])
            else:
                cmd.extend([
                    "-map", "0:a", 
                    "-map_metadata", "-1", "-map_metadata", "1", 
                    "-map_chapters", "1",
                    "-c:a", "copy"
                ])
            
            # Optimization: faststart
            cmd.extend(["-movflags", "+faststart"])
            cmd.append(str(output_path))

            # 6. Run FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            if process.stdout:
                buffer = ""
                while True:
                    chunk_bytes = await process.stdout.read(4096)
                    if not chunk_bytes:
                        break
                    
                    buffer += chunk_bytes.decode(errors="ignore")
                    if "\r" in buffer or "\n" in buffer:
                        lines = re.split(r'[\r\n]', buffer)
                        buffer = lines.pop()
                        for line in lines:
                            line = line.strip()
                            if line:
                                log_callback(line)
            
            return_code = await process.wait()
            
            if return_code == 0:
                final_path = lib / f"{safe_title}.m4b"
                try:
                    output_path.rename(final_path)
                except Exception:
                    pass
                return True
            return False
        except Exception as e:
            log_callback(f"[bold red]FFmpeg error: {e}[/]")
            return False
        finally:
            if meta_path and meta_path.exists():
                meta_path.unlink()

    def cleanup_sources(self, book: Audiobook, log_callback):
        """Deletes original files after conversion."""
        lib = self.library_path
        count = 0
        for pattern in [f"{book.asin}*", f"{book.safe_title}*"]:
            for ext in [".aax", ".json", ".jpg"]:
                for match in lib.glob(f"{pattern}{ext}"):
                    try:
                        match.unlink()
                        count += 1
                        log_callback(f"Deleted: {match.name}")
                    except Exception:
                        pass
        return count

    def play_audiobook(self, book: Audiobook):
        """Opens the finalized M4B file in the system default player."""
        import os
        safe_title = book.safe_title
        path = self.library_path / f"{safe_title}.m4b"
        
        if not path.exists():
            # Fallback to ASIN if safe_title doesn't exist
            path = self.library_path / f"{book.asin}.m4b"

        if not path.exists():
            return False, "M4B file not found."

        try:
            import platform
            if platform.system() == "Windows":
                os.startfile(str(path))
            elif platform.system() == "Darwin": # macOS
                subprocess.Popen(["open", str(path)])
            else: # Linux and others
                subprocess.Popen(["xdg-open", str(path)], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
            return True, None
        except Exception as e:
            return False, str(e)
