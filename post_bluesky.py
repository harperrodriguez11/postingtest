import os
import pickle
import random
import time
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from atproto import Client
from atproto_client.utils import TextBuilder


def get_creds():
    """Load token.pickle from repo root, refreshing the access token if it has expired."""
    with open("token.pickle", "rb") as token:
        creds = pickle.load(token)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def load_hashtag_sets(filepath="hashtags.txt"):
    """Return a list of hashtag sets (one per non-empty line)."""
    sets = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                sets.append(line)
    return sets


def pick_random_hashtags(filepath="hashtags.txt"):
    """Pick one random hashtag set; return list of tags without the # prefix."""
    hashtag_sets = load_hashtag_sets(filepath)
    if not hashtag_sets:
        return []
    chosen_line = random.choice(hashtag_sets)
    return [word.lstrip("#") for word in chosen_line.split() if word.startswith("#")]


def fetch_latest_video():
    creds = get_creds()
    service = build("drive", "v3", credentials=creds)
    folder_id = os.getenv("UPLOAD_FOLDER_ID")
    results = service.files().list(
        q=f"'{folder_id}' in parents",
        orderBy="createdTime desc",
        pageSize=5
    ).execute()
    files = results.get("files", [])
    if not files:
        print("No files found in upload folder.")
        return None, None
    for file in files:
        mime_type = file.get("mimeType", "")
        print(f"Found file: {file['name']} ({mime_type})")
        if mime_type.startswith("video/"):
            request = service.files().get_media(fileId=file["id"])
            local_path = f"/tmp/{file['name']}"
            with open(local_path, "wb") as f:
                f.write(request.execute())
            return file, local_path
    print("No video files found in upload folder.")
    return None, None


def move_file(file_id):
    creds = get_creds()
    service = build("drive", "v3", credentials=creds)
    upload_id = os.getenv("UPLOAD_FOLDER_ID")
    processed_id = os.getenv("PROCESSED_FOLDER_ID")
    service.files().update(
        fileId=file_id,
        addParents=processed_id,
        removeParents=upload_id
    ).execute()
    print("Moved file to processed folder.")


MAX_POST_LENGTH = 300  # Bluesky's grapheme limit per post
LOOP_INTERVAL_SECONDS = 1860  # 60 minutes between cycles

# ── Link definitions (replace URL when ready) ─────────────────────────────────
LINKS = [
    {"text": "👉 Live Girl",    "url": "https://lvx.teentoday.cfd/"},
    {"text": "👉 Fuck Me 1-on-1", "url": "https://lvx.teentoday.cfd/"},
]


def build_post(tags: list[str]) -> TextBuilder:
    """
    Final post layout:

        \n
        👉 Live Girl
        \n
        👉 Fuck Me 1-on-1
        \n
        \n
        #tag1 #tag2 #tag3 ...
    """
    tb = TextBuilder()

    # blank line at the very top
    tb.text("\n")

    # first link, blank line, second link
    tb.link(LINKS[0]["text"], LINKS[0]["url"])
    tb.text("\n\n")
    tb.link(LINKS[1]["text"], LINKS[1]["url"])

    # blank line then hashtags
    tb.text("\n\n")

    for i, tag in enumerate(tags):
        tb.tag(f"#{tag}", tag)
        if i < len(tags) - 1:
            tb.text(" ")

    return tb


def post_to_bluesky(video_name, local_path):
    handle = os.getenv("BSKY_HANDLE")
    app_pw = os.getenv("BSKY_APP_PW")
    client = Client()
    client.login(handle, app_pw)

    with open(local_path, "rb") as f:
        video_bytes = f.read()

    tags = pick_random_hashtags("hashtags.txt")
    text_builder = build_post(tags)

    client.send_video(
        text=text_builder,
        video=video_bytes,
        video_alt=video_name,
    )
    print("Posted to Bluesky:")
    print("  Links:", [l["text"] for l in LINKS])
    print("  Tags:", " ".join(f"#{t}" for t in tags))


def run_once():
    """Run a single fetch -> post -> move cycle."""
    file, local_path = fetch_latest_video()
    if not file:
        print("No new video this cycle.")
        return
    post_to_bluesky(file["name"], local_path)
    move_file(file["id"])
    # Clean up the local temp copy so disk doesn't fill up over a long-running loop
    try:
        os.remove(local_path)
    except OSError:
        pass


def main():
    """
    Loop forever, running one post cycle every LOOP_INTERVAL_SECONDS.
    Each cycle is wrapped in try/except so a single failure (e.g. a transient
    API error) doesn't kill the whole loop - it just gets logged and retried
    next cycle.
    """
    print(f"Starting loop. Posting every {LOOP_INTERVAL_SECONDS} seconds.")
    while True:
        cycle_start = time.time()
        try:
            run_once()
        except Exception as e:
            print(f"Error during cycle: {e}")

        elapsed = time.time() - cycle_start
        sleep_for = max(0, LOOP_INTERVAL_SECONDS - elapsed)
        print(f"Cycle done in {elapsed:.1f}s. Sleeping {sleep_for:.1f}s...")
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
