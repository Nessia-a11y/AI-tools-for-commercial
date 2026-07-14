"""Skill 7: Slide/PPT Translation

使用 AI 对 slide 和 PPT 文件中的文本内容进行语言翻译。
支持上传的演示文件翻译（中英互译）。
"""

import json
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "translations"
MANIFEST_PATH = DATA_DIR / "manifest.json"

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "translate_slide",
        "description": (
            "Translate slide/PPT content between languages. "
            "This tool extracts text from uploaded presentation files and translates them. "
            "Supports Chinese-English bidirectional translation. "
            "Use this when a user asks to translate a presentation, slide deck, or PPT file."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_file": {
                    "type": "string",
                    "description": "The filename or title of the slide/PPT to translate (must exist in external demos or datasheets)",
                },
                "target_language": {
                    "type": "string",
                    "enum": ["zh", "en", "ja", "ko"],
                    "description": "Target language code: 'zh' for Chinese, 'en' for English, 'ja' for Japanese, 'ko' for Korean",
                },
                "content_to_translate": {
                    "type": "string",
                    "description": "If the file cannot be parsed directly, paste the text content here for translation",
                },
            },
            "required": ["target_language"],
        },
    },
}

LANG_NAMES = {
    "zh": "中文",
    "en": "English",
    "ja": "日本語",
    "ko": "한국어",
}


def _load_manifest() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {"translations": []}


def _save_manifest(manifest: dict):
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def _find_source_file(source_file: str) -> dict | None:
    """Look up source file in external demos and datasheets."""
    # Check external demos
    ext_demos_path = Path(__file__).parent.parent / "data" / "external_demos" / "index.json"
    if ext_demos_path.exists():
        index = json.loads(ext_demos_path.read_text())
        for entry in index.get("files", []):
            if (source_file.lower() in entry.get("original_name", "").lower() or
                    source_file.lower() in entry.get("stored_name", "").lower()):
                return {
                    "title": entry.get("original_name", ""),
                    "path": str(Path(__file__).parent.parent / "data" / "external_demos" / entry["stored_name"]),
                    "type": "external_demo",
                }

    # Check datasheets
    ds_manifest_path = Path(__file__).parent.parent / "data" / "datasheets" / "manifest.json"
    if ds_manifest_path.exists():
        ds_manifest = json.loads(ds_manifest_path.read_text())
        for key, entry in ds_manifest.get("datasheets", {}).items():
            if (source_file.lower() in entry.get("title", "").lower() or
                    source_file.lower() in entry.get("filename", "").lower()):
                return {
                    "title": entry.get("title", ""),
                    "path": str(Path(__file__).parent.parent / "data" / "datasheets" / entry["filename"]),
                    "type": "datasheet",
                }

    return None


async def handle(arguments: dict) -> str:
    """Execute the translation skill."""
    source_file = arguments.get("source_file", "").strip()
    target_language = arguments.get("target_language", "zh").strip()
    content_to_translate = arguments.get("content_to_translate", "").strip()

    target_lang_name = LANG_NAMES.get(target_language, target_language)

    # If direct content is provided, return translation instruction
    if content_to_translate:
        manifest = _load_manifest()
        translation_record = {
            "source": source_file or "direct_input",
            "target_language": target_language,
            "input_length": len(content_to_translate),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        manifest["translations"].append(translation_record)
        _save_manifest(manifest)

        return (
            f"TRANSLATION_REQUEST:\n"
            f"Target language: {target_lang_name}\n"
            f"Source content ({len(content_to_translate)} characters):\n\n"
            f"{content_to_translate}\n\n"
            f"---\n"
            f"Please translate the above content to {target_lang_name}. "
            f"Maintain the original formatting, bullet points, and structure. "
            f"For technical terms (product names, protocols, standards), keep them in English with {target_lang_name} explanation in parentheses where helpful."
        )

    # If source file is specified, try to locate it
    if source_file:
        file_info = _find_source_file(source_file)
        if file_info:
            file_path = Path(file_info["path"])
            if file_path.exists():
                ext = file_path.suffix.lower()

                # For text-extractable formats
                if ext in (".txt", ".md", ".json"):
                    text_content = file_path.read_text(errors="ignore")[:10000]
                    return (
                        f"Found file: {file_info['title']}\n"
                        f"Type: {file_info['type']}\n"
                        f"Target language: {target_lang_name}\n\n"
                        f"TRANSLATION_REQUEST:\n"
                        f"Please translate the following content to {target_lang_name}:\n\n"
                        f"{text_content}"
                    )

                # For binary formats (PDF, PPTX) - instruct agent to handle
                if ext in (".pdf", ".pptx", ".ppt"):
                    return (
                        f"Found file: {file_info['title']}\n"
                        f"Type: {ext.upper()} ({file_info['type']})\n"
                        f"Path: {file_info['path']}\n"
                        f"Target language: {target_lang_name}\n\n"
                        f"This is a binary file ({ext}). To translate:\n"
                        f"1. The file is available at: /api/download/{'datasheet' if file_info['type'] == 'datasheet' else 'external'}/{file_path.name}\n"
                        f"2. Please ask the user to provide the text content from the slides they want translated,\n"
                        f"   or provide a summary/key points translation based on the file title and context.\n\n"
                        f"File title suggests this is about: {file_info['title']}\n"
                        f"Please provide a translated summary of key points about this topic in {target_lang_name}."
                    )

                return (
                    f"Found file: {file_info['title']}\n"
                    f"Format: {ext}\n"
                    f"Cannot directly extract text from this format. "
                    f"Please ask the user to paste the text content they want translated."
                )
            else:
                return f"File record found but file is missing on disk: {file_info['title']}"

        return (
            f"Could not find file '{source_file}' in the library.\n"
            f"Available sources to search:\n"
            f"- External demos (uploaded presentations)\n"
            f"- Datasheets (uploaded PDFs)\n\n"
            f"Please ask the user to:\n"
            f"1. Provide the exact filename, or\n"
            f"2. Paste the text content directly for translation"
        )

    return (
        f"Please specify what to translate:\n"
        f"- Provide a 'source_file' name to translate an existing file, or\n"
        f"- Provide 'content_to_translate' with the text to translate\n"
        f"Target language: {target_lang_name}"
    )
