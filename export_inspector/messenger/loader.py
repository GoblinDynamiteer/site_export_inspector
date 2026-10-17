"""Discover and load Messenger threads from JSON files, ZIP exports or folders."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from export_inspector.messenger.formatting import repair_text, signature_label


def participant_signature_from_data(data: dict) -> tuple[str, ...]:
    names: set[str] = set()
    for participant in data.get("participants", []):
        if isinstance(participant, str):
            name = repair_text(participant).strip()
        else:
            name = repair_text(participant.get("name", "")).strip()
        if name:
            names.add(name)
    return tuple(sorted(names))


def participant_signature_from_message(message: dict) -> tuple[str, ...]:
    sender = repair_text(message.get("sender_name", "")).strip()
    return (sender,) if sender else ()


def message_sort_key(message: dict) -> tuple[int, str, str]:
    return (
        int(message.get("timestamp_ms", 0)),
        repair_text(message.get("sender_name", "")).strip(),
        repair_text(message.get("content", "")).strip(),
    )


def message_dedupe_key(message: dict) -> tuple:
    attachments: list[tuple[str, str]] = []
    for key in ("photos", "videos", "gifs", "audio_files", "files"):
        for item in message.get(key) or []:
            attachments.append((key, repair_text(item.get("uri", "")).strip()))

    sticker = ""
    if message.get("sticker"):
        sticker = repair_text((message.get("sticker") or {}).get("uri", "")).strip()

    share = message.get("share") or {}
    share_key = (
        repair_text(share.get("link", "")).strip(),
        repair_text(share.get("share_text", "")).strip(),
    )

    reactions = tuple(
        sorted(
            (
                repair_text(reaction.get("actor", "")).strip(),
                repair_text(reaction.get("reaction", "")).strip(),
            )
            for reaction in (message.get("reactions") or [])
        )
    )

    return (
        int(message.get("timestamp_ms", 0)),
        repair_text(message.get("sender_name", "")).strip(),
        repair_text(message.get("content", "")).strip(),
        tuple(sorted(attachments)),
        sticker,
        share_key,
        int(message.get("call_duration") or 0),
        reactions,
    )


def is_messenger_thread_json_path(path_text: str) -> bool:
    lower = path_text.lower().replace("\\", "/")
    file_name = Path(lower).name
    if "/your_facebook_activity/messages/" in lower:
        return file_name.startswith("message_") and file_name.endswith(".json")
    if "/" not in lower.strip("/") and file_name.endswith(".json") and "_" in file_name:
        return True
    return False


def normalize_message(message: dict) -> dict:
    if "timestamp_ms" in message:
        return message

    normalized: dict = {
        "timestamp_ms": int(message.get("timestamp", 0)),
        "sender_name": repair_text(message.get("senderName", "Unknown")).strip() or "Unknown",
        "content": repair_text(message.get("text", "")).strip(),
    }

    media = message.get("media") or []
    if media:
        normalized["files"] = [
            {"uri": repair_text(item.get("uri", "")).strip()}
            for item in media
            if repair_text(item.get("uri", "")).strip()
        ]

    reactions = message.get("reactions") or []
    if reactions:
        normalized["reactions"] = [
            {
                "actor": repair_text(reaction.get("actor", "")).strip(),
                "reaction": repair_text(reaction.get("reaction", "")).strip(),
            }
            for reaction in reactions
        ]

    if message.get("isUnsent") and not normalized["content"]:
        normalized["content"] = "[Message unsent]"

    return normalized


def load_json_thread(path: Path) -> tuple[list[dict], tuple[str, ...]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = [normalize_message(message) for message in data.get("messages", [])]
    return messages, participant_signature_from_data(data)


def load_zip_thread_members(
    path: Path,
    target_signatures: set[tuple[str, ...]],
) -> list[tuple[str, tuple[str, ...], list[dict]]]:
    matched_threads: list[tuple[str, tuple[str, ...], list[dict]]] = []

    with zipfile.ZipFile(path) as archive:
        for member_name in sorted(archive.namelist()):
            if not is_messenger_thread_json_path(member_name):
                continue
            try:
                data = json.loads(archive.read(member_name).decode("utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict) or "participants" not in data or "messages" not in data:
                continue
            signature = participant_signature_from_data(data)
            if target_signatures and signature not in target_signatures:
                continue
            matched_threads.append(
                (
                    member_name,
                    signature,
                    [normalize_message(message) for message in data.get("messages", [])],
                )
            )

    return matched_threads


def discover_folder_sources(folder: Path) -> tuple[list[Path], list[Path], set[tuple[str, ...]]]:
    json_paths = sorted(path for path in folder.rglob("message_*.json") if path.is_file())
    zip_paths = sorted(path for path in folder.rglob("*.zip") if path.is_file())

    target_signatures: set[tuple[str, ...]] = set()
    for path in json_paths:
        try:
            _messages, signature = load_json_thread(path)
        except Exception:
            continue
        if signature:
            target_signatures.add(signature)

    return json_paths, zip_paths, target_signatures


def discover_threads(input_path: str | None) -> list[tuple[tuple[str, ...], list[str]]]:
    """List the threads in a JSON file, ZIP export or folder (or `message_*.json` in the
    working directory when `input_path` is None) as (participants, source labels) pairs,
    sorted by participant label. Unreadable JSON files in folders are skipped."""
    thread_sources: dict[tuple[str, ...], list[str]] = {}

    def add_thread(signature: tuple[str, ...], source_label: str) -> None:
        if not signature:
            return
        thread_sources.setdefault(signature, []).append(source_label)

    if input_path:
        selected_path = Path(input_path)
        if selected_path.is_dir():
            json_paths, zip_paths, _target_signatures = discover_folder_sources(selected_path)
            for path in json_paths:
                try:
                    _messages, signature = load_json_thread(path)
                except Exception:
                    continue
                add_thread(signature, str(path))

            for path in zip_paths:
                for member_name, signature, _messages in load_zip_thread_members(path, set()):
                    add_thread(signature, f"{path}!{member_name}")
        elif selected_path.suffix.lower() == ".zip":
            for member_name, signature, _messages in load_zip_thread_members(selected_path, set()):
                add_thread(signature, f"{selected_path}!{member_name}")
        else:
            messages, signature = load_json_thread(selected_path)
            if messages:
                add_thread(signature, str(selected_path))
    else:
        for path in sorted(Path.cwd().glob("message_*.json")):
            try:
                _messages, signature = load_json_thread(path)
            except Exception:
                continue
            add_thread(signature, str(path))

    return sorted(thread_sources.items(), key=lambda item: signature_label(item[0]).lower())


def load_exports(
    input_path: str | None,
    target_signature: tuple[str, ...] | None = None,
) -> tuple[list[dict], list[str], list[str]]:
    """Load the messages of one thread or all threads: (messages, participants, sources).

    Inputs are as for `discover_threads`; `target_signature` limits loading to one thread.
    Messages are deduplicated and sorted by time. Raises FileNotFoundError when nothing
    was found.
    """
    all_messages: list[dict] = []
    participants: set[str] = set()
    source_labels: list[str] = []

    if input_path:
        selected_path = Path(input_path)
        if selected_path.is_dir():
            json_paths, zip_paths, target_signatures = discover_folder_sources(selected_path)
            if target_signature is not None:
                target_signatures = {target_signature}
            for path in json_paths:
                messages, signature = load_json_thread(path)
                if target_signature is not None and signature != target_signature:
                    continue
                all_messages.extend(messages)
                participants.update(signature)
                source_labels.append(str(path))

            for path in zip_paths:
                matched_threads = load_zip_thread_members(path, target_signatures)
                for member_name, signature, messages in matched_threads:
                    all_messages.extend(messages)
                    participants.update(signature)
                    source_labels.append(f"{path}!{member_name}")
        elif selected_path.suffix.lower() == ".zip":
            zip_targets = {target_signature} if target_signature is not None else set()
            matched_threads = load_zip_thread_members(selected_path, zip_targets)
            for member_name, signature, messages in matched_threads:
                all_messages.extend(messages)
                participants.update(signature)
                source_labels.append(f"{selected_path}!{member_name}")
        else:
            messages, signature = load_json_thread(selected_path)
            if target_signature is not None and signature != target_signature:
                messages = []
                signature = ()
            all_messages.extend(messages)
            participants.update(signature)
            if messages:
                source_labels.append(str(selected_path))
    else:
        json_paths = sorted(Path.cwd().glob("message_*.json"))
        for path in json_paths:
            messages, signature = load_json_thread(path)
            if target_signature is not None and signature != target_signature:
                continue
            all_messages.extend(messages)
            participants.update(signature)
            source_labels.append(str(path))

    if not source_labels:
        raise FileNotFoundError("No Messenger message JSON files or Messenger export ZIPs found.")

    deduped: dict[tuple, dict] = {}
    for message in all_messages:
        deduped[message_dedupe_key(message)] = message

    messages = sorted(deduped.values(), key=message_sort_key)
    return messages, sorted(participants), source_labels
