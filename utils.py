import re

def sanitize_filename(text: str) -> str:
    """
    Sanitizes a string for use as a filename:
    1. Removes or replaces characters that are generally problematic on Windows/Linux/macOS.
    2. Replaces spaces with underscores.
    3. Collapses multiple dashes/underscores.
    4. Truncates to a reasonable length.
    """
    if not text:
        return "unnamed_audiobook"
        
    # Replace characters that are invalid in Windows or problematic elsewhere
    # < > : " / \ | ? *
    text = re.sub(r'[<>:"/\\|?*]', '-', text)
    
    # Replace other non-alphanumeric (except . - _) with a dash
    text = re.sub(r'[^\w\.\- ]', '-', text)
    
    # Replace spaces with underscores
    text = text.replace(' ', '_')
    
    # Collapse multiple dashes or underscores
    text = re.sub(r'[\-_]{2,}', '_', text)
    
    # Remove leading/trailing dashes or underscores
    text = text.strip('-_')
    
    # Truncate to avoid issues with long paths (leaving room for extension)
    return text[:200] if text else "unnamed_audiobook"

def convert_chapters_json_to_ffmetadata(json_data: dict, tags: dict = None) -> list[str]:
    """Converts Audible chapter JSON to FFMETADATA format with optional global tags."""
    def _escape(text: str) -> str:
        return text.translate(
            str.maketrans({
                "\\": r"\\",
                "\n": r"\\n",
                "#":  r"\#",
                ";":  r"\;",
                "=":  r"\="
            }))

    def _convert_recursive(chapters: list[dict]) -> list[str]:
        output = []
        for item in chapters:
            start_time = int(item['start_offset_ms'])
            duration = int(item['length_ms'])
            end_time = start_time + duration
            title_str = _escape(str(item['title']))
            
            output.append("")
            output.append("[CHAPTER]")
            output.append("TIMEBASE=1/1000")
            output.append(f"START={start_time}")
            output.append(f"END={end_time}")
            output.append(f"TITLE={title_str}")
            if "chapters" in item:
                output.extend(_convert_recursive(item['chapters']))
        return output

    output_list = [";FFMETADATA1"]
    
    # Add Global Tags
    if tags:
        for key, val in tags.items():
            if val:
                output_list.append(f"{key.upper()}={_escape(str(val))}")

    chapters = json_data['content_metadata']['chapter_info']['chapters']
    output_list.extend(_convert_recursive(chapters))
    return output_list
