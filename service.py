import asyncio
import json
import re
import tempfile
import platform
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Callable
from models import Audiobook
from utils import sanitize_filename, convert_chapters_json_to_ffmetadata
from exceptions import AudibleAPIError, AuthenticationError

class AudiobookService:
    def __init__(self, config: Dict):
        self.config = config
        self._active_processes: List[asyncio.subprocess.Process] = []

    async def _run_process(self, *args, **kwargs) -> asyncio.subprocess.Process:
        """Helper to run a subprocess and track it."""
        # Clean up any already finished processes to avoid memory leaks
        self._active_processes = [p for p in self._active_processes if p.returncode is None]
        
        process = await asyncio.create_subprocess_exec(*args, **kwargs)
        self._active_processes.append(process)
        return process

    async def shutdown(self):
        """Terminates all active subprocesses with a timeout and kill fallback."""
        if not self._active_processes:
            return

        # 1. Try graceful termination
        for process in self._active_processes:
            if process.returncode is None:
                try:
                    process.terminate()
                except Exception:
                    pass
        
        # 2. Wait for a short period
        wait_tasks = [asyncio.create_task(p.wait()) for p in self._active_processes if p.returncode is None]
        pending = set()
        if wait_tasks:
            _, pending = await asyncio.wait(wait_tasks, timeout=3.0)
        
        # 3. Force kill any remaining processes
        if pending:
            for process in self._active_processes:
                if process.returncode is None:
                    try:
                        process.kill()
                    except Exception:
                        pass
            
            # Final wait for killed processes
            await asyncio.gather(*(p.wait() for p in self._active_processes if p.returncode is None), return_exceptions=True)
            
        self._active_processes.clear()

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
            process = await self._run_process(
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

    def get_status_map(self, books: List[Audiobook]) -> Dict[str, str]:
        """Returns a map of ASIN to status string for a list of books efficiently."""
        lib = self.library_path
        if not lib.exists():
            return {}

        file_set = {f.name for f in lib.iterdir()}
        status_map = {}
        
        # Pre-calculate base names for fast lookup
        # Map base name (ASIN or safe title) to the most advanced status found
        # priority: m4b > aax
        base_status = {}
        
        for f in file_set:
            if f.endswith(".m4b"):
                name = f[:-4]
                base_status[name] = "✔"
            elif f.endswith(".aax"):
                # Handle ASIN_ascii.aax, ASIN.part1.aax, etc.
                name = f.split(".")[0]
                if base_status.get(name) != "✔":
                    base_status[name] = "⬇"

        for book in books:
            asin = book.asin
            safe_title = book.safe_title
            
            # Check for M4B first
            if base_status.get(asin) == "✔" or base_status.get(safe_title) == "✔":
                status_map[asin] = "[bold green]✔[/]"
                continue
            
            # Check for AAX
            found_aax = False
            search_keys = [asin, safe_title] + (book.parts or [])
            for key in search_keys:
                if base_status.get(key) == "⬇":
                    found_aax = True
                    break
            
            if found_aax:
                status_map[asin] = "[bold yellow]⬇[/]"
            else:
                status_map[asin] = ""
                
        return status_map

    def get_status(self, asin: str, title: str, file_set: Optional[set] = None, parts: List[str] = None) -> str:
        """Checks the filesystem for the status of a book."""
        safe_title = sanitize_filename(title)
        lib = self.library_path

        if file_set is None:
            if not lib.exists():
                return ""
            file_set = {f.name for f in lib.iterdir()}

        # Check for M4B
        if f"{safe_title}.m4b" in file_set or f"{asin}.m4b" in file_set:
            return "[bold green]✔[/]"
        
        # Check for AAX
        search_keys = [asin, safe_title] + (parts or [])
        for f in file_set:
            if f.endswith(".aax"):
                base = f.split(".")[0]
                if base in search_keys:
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
                "-p", "response_groups=product_details,product_desc,contributors,series,relationships"
            ]
            process = await self._run_process(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise AudibleAPIError(f"Audible API failed: {stderr.decode().strip()}")

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
                    # If multiple series, try to find one with a sequence number
                    # as it's usually the more specific/primary one
                    primary_series = series_list[0]
                    for s in series_list:
                        if s.get("sequence"):
                            primary_series = s
                            break
                    series_title = primary_series.get("title", "")
                    series_sequence = primary_series.get("sequence", "")

                # Extract parts (relationships)
                parts = []
                relationships = item.get("relationships") or []
                # Sort components by 'sort' field if available to ensure correct order
                components = [r for r in relationships if r.get("relationship_type") == "component"]
                if components:
                    # Sort by the 'sort' key, which is usually a string representation of the part number
                    components.sort(key=lambda x: int(x.get("sort", "0")) if x.get("sort", "").isdigit() else 0)
                    parts = [c.get("asin") for c in components if c.get("asin")]

                status = self.get_status(asin, title, file_set=file_set, parts=parts)
                
                books.append(Audiobook(
                    asin=asin,
                    author=author,
                    title=title,
                    narrator=narrator,
                    year=year,
                    duration_ms=duration_ms,
                    series_title=series_title,
                    series_sequence=series_sequence,
                    status=status,
                    parts=parts
                ))
                    
            return books
        except Exception as e:
            if isinstance(e, (AudibleAPIError, AuthenticationError)):
                raise
            raise AudibleAPIError(f"Unexpected error fetching library: {e}") from e

    async def download(self, asin: str, log_callback: Callable[[str], None]) -> int:
        """Runs the audible download command asynchronously."""
        cmd = ["audible", "download", "-a", asin, "--aax", "--cover", "--chapter", "--filename-mode", "asin_ascii", "-y"]
        process = await self._run_process(
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

    async def merge_aax_parts(self, aax_files: List[Path], activation_bytes: str, log_callback: Callable[[str], None]) -> Optional[Path]:
        """Decrypts and merges multiple AAX parts into a single M4A file."""
        temp_m4as = []
        merged_m4a = None
        concat_path = None
        
        try:
            for i, aax_path in enumerate(aax_files):
                # Use the same directory as the first AAX for temp files to ensure enough space
                temp_m4a = aax_path.with_suffix(f".part{i}.tmp.m4a")
                temp_m4as.append(temp_m4a)
                
                log_callback(f"Decrypting part {i+1}/{len(aax_files)}: {aax_path.name}...")
                cmd = ["ffmpeg", "-y", "-activation_bytes", activation_bytes, "-i", str(aax_path), "-c:a", "copy", "-vn", str(temp_m4a)]
                
                process = await self._run_process(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT
                )
                await process.wait()
                if process.returncode != 0:
                    log_callback(f"[bold red]Failed to decrypt part {i+1}[/]")
                    return None

            # Create concat file for FFmpeg
            concat_path = aax_files[0].with_suffix(".concat.tmp.txt")
            with open(concat_path, "w", encoding="utf-8") as f:
                for m4a in temp_m4as:
                    # FFmpeg concat file expects escaped paths or relative paths
                    f.write(f"file '{m4a.name}'\n")

            merged_m4a = aax_files[0].with_suffix(".merged.tmp.m4a")
            log_callback("Merging all parts...")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(merged_m4a)]
            
            process = await self._run_process(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            await process.wait()
            
            if process.returncode != 0:
                log_callback("[bold red]Failed to merge parts[/]")
                return None
                
            return merged_m4a

        except Exception as e:
            log_callback(f"[bold red]Merge error: {e}[/]")
            return None
        finally:
            # Cleanup intermediate temp files
            for m4a in temp_m4as:
                if m4a.exists():
                    try: m4a.unlink()
                    except: pass
            if concat_path and concat_path.exists():
                try: concat_path.unlink()
                except: pass

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
        aax_files = []
        search_asins = [book.asin] + (book.parts or [])
        for s_asin in search_asins:
            matches = list(lib.glob(f"{s_asin}*.aax"))
            for m in matches:
                if m not in aax_files:
                    aax_files.append(m)
        
        # Also try safe_title if no ASIN matches or to find more parts
        title_matches = list(lib.glob(f"*{safe_title}*.aax"))
        for tm in title_matches:
            # For title matches, be a bit more selective to avoid matching other books
            # If it contains "Part", it's likely a part of this book if the title matches
            if tm not in aax_files:
                if any(s_asin in tm.name for s_asin in search_asins) or "Part" in tm.name:
                    aax_files.append(tm)
        
        if not aax_files:
            log_callback("[bold red]AAX file(s) not found.[/]")
            return False

        # Sort files to ensure parts are in order
        # We sort by filename, but try to handle numeric part numbers
        def sort_key(path):
            name = path.name
            # Look for "Part X" or "_X"
            part_match = re.search(r"[Pp]art[ _]?(\d+)", name)
            if part_match:
                return int(part_match.group(1))
            # Fallback to string sort
            return name

        aax_files.sort(key=sort_key)

        aax_input_path = None
        temp_merged_path = None
        
        if len(aax_files) > 1:
            temp_merged_path = await self.merge_aax_parts(aax_files, self.activation_bytes, log_callback)
            if not temp_merged_path:
                return False
            aax_input_path = temp_merged_path
        else:
            aax_input_path = aax_files[0]

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
            
            # If we merged parts, the input is already decrypted M4A
            # Otherwise, it's a single AAX that needs activation_bytes
            if temp_merged_path:
                cmd = ["ffmpeg", "-y", "-i", str(aax_input_path), "-f", "ffmetadata", "-i", str(meta_path)]
            else:
                cmd = ["ffmpeg", "-y", "-activation_bytes", self.activation_bytes, "-i", str(aax_input_path), "-f", "ffmetadata", "-i", str(meta_path)]
            
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
            process = await self._run_process(
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
            if temp_merged_path and temp_merged_path.exists():
                try: temp_merged_path.unlink()
                except: pass

    def cleanup_sources(self, book: Audiobook, log_callback):
        """Deletes original files after conversion."""
        lib = self.library_path
        count = 0
        search_asins = [book.asin] + (book.parts or [])
        patterns = [f"{s_asin}*" for s_asin in search_asins] + [f"{book.safe_title}*"]
        
        for pattern in patterns:
            for ext in [".aax", ".json", ".jpg"]:
                for match in lib.glob(f"{pattern}{ext}"):
                    try:
                        match.unlink()
                        count += 1
                        log_callback(f"[dim]Deleted: {match.name}[/]")
                    except Exception:
                        pass
        return count

    def play_audiobook(self, book: Audiobook):
        """Opens the finalized M4B file in the system default player."""
        safe_title = book.safe_title
        path = self.library_path / f"{safe_title}.m4b"
        
        if not path.exists():
            # Fallback to ASIN if safe_title doesn't exist
            path = self.library_path / f"{book.asin}.m4b"

        if not path.exists():
            return False, "M4B file not found."

        try:
            if platform.system() == "Windows":
                os.startfile(str(path))
            elif platform.system() == "Darwin": # macOS
                subprocess.Popen(["open", str(path)])
            else: # Linux and others
                subprocess.Popen(["xdg-open", str(path)], stderr=os.devnull, stdout=os.devnull)
            return True, None
        except Exception as e:
            return False, str(e)
