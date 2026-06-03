import re
from core.utils.logger import logger

def merge_broken_paragraphs(text: str) -> str:
    lines = text.split("\n")
    processed_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        
        if re.match(r"^=== Pagina \d+ ===$", line):
            processed_lines.append(line)
            i += 1
            continue

        if line.endswith("-") and i + 1 < len(lines):
            next_line = lines[i+1].lstrip()
            if next_line and next_line[0].islower():
                line = line[:-1] + next_line
                i += 1
        
        elif line and line[-1] not in ".!?:;\"" and i + 1 < len(lines):
            next_line = lines[i+1].lstrip()
            if next_line and not re.match(r"^=== Pagina \d+ ===$", next_line) and next_line[0].islower():
                line = line + " " + next_line
                i += 1
                
        processed_lines.append(line)
        i += 1
        
    return "\n".join(processed_lines)

def parse_markdown_and_descriptions(text: str):
    desc_pattern = r"\[DESCRIÇÃO:\s*(.*?)\]"
    
    paragraphs = text.split("\n\n")
    structured_content = []
    
    for para in paragraphs:
        para = para.strip()
        if not para: continue
        
        desc_match = re.fullmatch(desc_pattern, para, re.DOTALL | re.IGNORECASE)
        if desc_match:
            structured_content.append(('description', desc_match.group(1).strip()))
            continue
            
        if para.startswith("### "):
            structured_content.append(('h3', para[4:].strip()))
        elif para.startswith("## "):
            structured_content.append(('h2', para[3:].strip()))
        elif para.startswith("# "):
            structured_content.append(('h1', para[2:].strip()))
        else:
            lines = para.split("\n")
            for line in lines:
                line = line.strip()
                if not line: continue
                
                if re.search(desc_pattern, line, re.IGNORECASE):
                    parts = re.split(desc_pattern, line, flags=re.IGNORECASE)
                    for idx, part in enumerate(parts):
                        part = part.strip()
                        if not part: continue
                        if idx % 2 == 1:
                            structured_content.append(('description', part))
                        else:
                            structured_content.append(('text', part))
                    continue

                if line.startswith(("- ", "* ")):
                    structured_content.append(('bullet', line[2:].strip()))
                elif re.match(r"^\d+\.\s", line):
                    parts = line.split(". ", 1)
                    structured_content.append(('number', parts[1].strip()))
                else:
                    structured_content.append(('text', line))
                    
    return structured_content

def apply_formatting(paragraph_obj, text, bold_font=None, italic_font=None):
    pattern = r"(\*\*\*.*?\*\*\*|\*\*.*?\*\*|\*.*?\*)"
    parts = re.split(pattern, text)
    return parts
