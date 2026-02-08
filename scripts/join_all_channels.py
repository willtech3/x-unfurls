#!/usr/bin/env python3
"""Join the X Unfurls bot to all public channels in the workspace."""

import os
import sys
import time

import httpx

BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
if not BOT_TOKEN:
    print("Error: SLACK_BOT_TOKEN not set")
    sys.exit(1)

BASE_URL = "https://slack.com/api"
HEADERS = {"Authorization": f"Bearer {BOT_TOKEN}"}


def list_all_channels() -> list[dict]:
    """Fetch all public channels via pagination."""
    channels = []
    cursor = None
    while True:
        params: dict = {"types": "public_channel", "limit": 200, "exclude_archived": "true"}
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(f"{BASE_URL}/conversations.list", headers=HEADERS, params=params)
        data = resp.json()
        if not data.get("ok"):
            print(f"Error listing channels: {data.get('error')}")
            sys.exit(1)
        channels.extend(data.get("channels", []))
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels


def join_channel(channel_id: str) -> str:
    """Join a channel. Returns 'joined', 'already', or error string."""
    resp = httpx.post(
        f"{BASE_URL}/conversations.join",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={"channel": channel_id},
    )
    data = resp.json()
    if data.get("ok"):
        if data.get("already_in_channel"):
            return "already"
        return "joined"
    return data.get("error", "unknown_error")


def main() -> None:
    print("Fetching all public channels...")
    channels = list_all_channels()
    print(f"Found {len(channels)} public channels\n")

    joined = 0
    already = 0
    errors = 0

    for ch in channels:
        name = ch["name"]
        cid = ch["id"]
        result = join_channel(cid)
        if result == "joined":
            print(f"  + Joined #{name}")
            joined += 1
        elif result == "already":
            print(f"  = Already in #{name}")
            already += 1
        else:
            print(f"  ! Error joining #{name}: {result}")
            errors += 1
        # Rate limit: ~1 req/sec to stay under Slack tier limits
        time.sleep(0.5)

    print(f"\nDone: {joined} joined, {already} already in, {errors} errors")


if __name__ == "__main__":
    main()
