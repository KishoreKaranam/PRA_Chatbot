# Script 1: public API server.
# Accepts a POST call with a list of files, validates and stores them,
# then hands the accepted files to script2 (LLM agent) and waits for
# its result before answering the external caller.

from flask import Flask, request, jsonify
from utils.logger import get_logger
from utils.validation import get_extension, is_supported, save_file
from scripts.script2_llm_agent import process_files
from config.settings import API_HOST, API_PORT

app = Flask(__name__)
logger = get_logger(__name__)


@app.route("/upload", methods=["POST"])
def upload():
    """Receive a list of files, validate and store the supported ones,
    then trigger the LLM agent to process them."""

    body = request.get_json(silent=True) or {}
    files = body.get("files", [])
    logger.info(f"received request with {len(files)} file(s)")

    accepted = []   # list of {"path", "extension", "filename"} for saved files
    rejected_and_failed = []   # list of {"filename", "reason"} for files we could not accept

    # --- Step 1: validate and store each file ---
    for item in files:
        filename = item.get("filename", "")
        mime_type = item.get("mime_type", "")
        content_base64 = item.get("content", "")

        extension = get_extension(filename)

        if not is_supported(extension, mime_type):
            logger.info(f"rejected file '{filename}': unsupported format/mime '{mime_type}'")
            rejected_and_failed.append({"filename": filename, "reason": "unsupported format or mime type"})
            continue

        try:
            saved_path = save_file(filename, extension, content_base64)
            logger.info(f"stored file '{filename}' at '{saved_path}'")
            accepted.append({"path": saved_path, "extension": extension, "filename": filename})
        except Exception as e:
            logger.info(f"failed to store file '{filename}': {e}")
            rejected_and_failed.append({"filename": filename, "reason": f"failed to store: {e}"})

    # --- Step 2: hand accepted files to the LLM agent (script2) and wait ---
    agent_result = {"processed": [], "failed": []}
    if accepted:
        logger.info(f"calling agent for {len(accepted)} accepted file(s)")
        agent_result = process_files(accepted)
        logger.info(f"agent responded: processed={len(agent_result['processed'])}, failed={len(agent_result['failed'])}")

    # --- Step 3: build the response for the external caller ---
    rejected_and_failed.extend({"filename": f, "reason": "not processed by agent"} for f in agent_result["failed"])
    response = {
        "successful": agent_result["processed"],
        "failed": rejected_and_failed,
    }

    logger.info(f"responding: successful={len(response['successful'])}, failed={len(response['failed'])}")
    return jsonify(response)


if __name__ == "__main__":
    app.run(host=API_HOST, port=API_PORT)
