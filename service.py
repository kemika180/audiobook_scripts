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
        return self.config.get("activation_bytes", "")

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

    def verify_file_exists(self, path: Path, timeout: float = 2.0) -> bool:
        """Polls for a file's existence for a limited time."""
        import time
        start = time.time()
        while time.time() - start < timeout:
            if path.exists():
                return True
            time.sleep(0.1)
        return False

    def fetch_library(self) -> List[Audiobook]:
        """Fetches the library using audible-cli with a robust regex parser."""
        try:
            output = subprocess.check_output(
                ["audible", "library", "list"], 
                text=True, 
                stderr=subprocess.PIPE
            )
            books = []
            
            # Pre-list directory for faster status checks
            lib = self.library_path
            file_set = {f.name for f in lib.iterdir()} if lib.exists() else set()

            # Pattern: ASIN: Author: Title
            pattern = re.compile(r'^([^:]+):\s*([^:]+):\s*(.*)$')
            
            for line in output.strip().split('\n'):
                if not line: continue
                
                match = pattern.match(line)
                if match:
                    asin, author, title = match.groups()
                    status = self.get_status(asin.strip(), title.strip(), file_set=file_set)
                    books.append(Audiobook(
                        asin=asin.strip(), 
                        author=author.strip(), 
                        title=title.strip(), 
                        status=status
                    ))
                else:
                    # Fallback for lines that don't match the 3-part format
                    parts = line.split(': ', 1)
                    if len(parts) == 2:
                        asin, title = parts
                        status = self.get_status(asin.strip(), title.strip(), file_set=file_set)
                        books.append(Audiobook(
                            asin=asin.strip(), 
                            author="Unknown", 
                            title=title.strip(), 
                            status=status
                        ))
                    
            return books
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Audible CLI failed: {e.stderr.strip() if e.stderr else e}") from e
        except Exception as e:
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

        # 4. Prepare Metadata
        try:
            with open(json_path, 'r') as f:
                json_data = json.load(f)
            ffmetadata = convert_chapters_json_to_ffmetadata(json_data)
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp_meta:
                tmp_meta.write('\n'.join(ffmetadata))
                meta_path = Path(tmp_meta.name)
            log_callback(f"Prepared metadata: {meta_path.name}")
        except Exception as e:
            log_callback(f"[bold red]Metadata error: {e}[/]")
            return False

        # 5. Build FFmpeg command
        output_path = lib / f"{book.asin}.m4b"
        cmd = ["ffmpeg", "-y", "-activation_bytes", self.activation_bytes, "-i", str(aax_path), "-i", str(meta_path)]
        if cover_path:
            cmd.extend(["-i", str(cover_path), "-map_metadata", "0", "-map_chapters", "1", "-map", "0:a", "-map", "2:v", "-c:a", "copy", "-c:v", "copy", "-disposition:v:0", "attached_pic"])
        else:
            cmd.extend(["-map_metadata", "0", "-map_chapters", "1", "-map", "0:a", "-c:a", "copy"])
        cmd.append(str(output_path))

        # 6. Run FFmpeg
        try:
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
            
            if meta_path.exists(): meta_path.unlink()

            if return_code == 0:
                final_path = lib / f"{safe_title}.m4b"
                try:
                    output_path.rename(final_path)
                except Exception:
                    pass
                return True
            return False
        except Exception as e:
            if 'meta_path' in locals() and meta_path.exists(): meta_path.unlink()
            log_callback(f"[bold red]FFmpeg error: {e}[/]")
            return False

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
