# Helper functions used by script1 to validate incoming file entries.

import base64
import os
import uuid
from config.settings import SUPPORTED_FORMATS, UPLOAD_DIR


def get_extension(filename):
    """Return the lowercase extension of a filename without the dot."""
    _, ext = os.path.splitext(filename)
    return ext.lower().lstrip(".")


def is_supported(extension, mime_type):
    """Check that extension is known and the given MIME type matches it."""
    allowed_mimes = SUPPORTED_FORMATS.get(extension)
    if allowed_mimes is None:
        return False
    return mime_type in allowed_mimes


def save_file(filename, extension, content_base64):
    """Decode base64 content and save it under storage/uploads with a unique name.

    Returns the full path of the saved file.
    """
    raw_bytes = base64.b64decode(content_base64)

    # Prefix with a uuid to avoid name collisions between uploads.
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    full_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(full_path, "wb") as f:
        f.write(raw_bytes)

    return full_path
