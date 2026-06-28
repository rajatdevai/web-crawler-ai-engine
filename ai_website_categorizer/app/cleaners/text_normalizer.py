import html
import re
import unicodedata


class TextNormalizer:
    # Zero-width and invisible Unicode characters
    INVISIBLE_CHARS = re.compile(
        r'[\u200b\u200c\u200d\u200e\u200f\u00ad\ufeff\u2028\u2029\u00a0]+'
    )
    # Multiple whitespace (but preserve newlines in first pass)
    MULTI_SPACE = re.compile(r'[ \t]+')
    # Multiple blank lines
    MULTI_NEWLINE = re.compile(r'\n{3,}')
    # Repeated punctuation like "!!!!!" or "....."
    REPEATED_PUNCT = re.compile(r'([!?.,-])\1{2,}')

    def normalize(self, text: str) -> str:
        """Apply all normalization steps in sequence."""
        if not text:
            return ""

        # Step 1: Decode HTML entities
        text = html.unescape(text)

        # Step 2: Normalize Unicode to NFC
        text = unicodedata.normalize("NFC", text)

        # Step 3: Remove invisible/zero-width characters
        text = self.INVISIBLE_CHARS.sub(" ", text)

        # Step 4: Collapse horizontal whitespace (preserve newlines)
        text = self.MULTI_SPACE.sub(" ", text)

        # Step 5: Remove repeated punctuation
        text = self.REPEATED_PUNCT.sub(r'\1', text)

        # Step 6: Process lines
        lines = text.splitlines()
        cleaned_lines = []
        prev_line = None
        for line in lines:
            line = line.strip()

            # Skip empty lines
            if not line:
                cleaned_lines.append("")
                continue

            # Skip lines shorter than 3 chars (unless they're standalone numbers)
            if len(line) < 3 and not line.isdigit():
                continue

            # Deduplicate consecutive identical lines
            if line == prev_line:
                continue

            cleaned_lines.append(line)
            prev_line = line

        # Step 7: Collapse multiple blank lines to max one
        text = "\n".join(cleaned_lines)
        text = self.MULTI_NEWLINE.sub("\n\n", text)

        return text.strip()
