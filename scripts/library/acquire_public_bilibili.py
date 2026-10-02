"""Resolve expressly downloadable public replays; never persist CDN signatures.

No cookies, logins, alternate clients, proxy rotation, quality unlocking, or
authentication flows. A changed source or denial fails closed.
"""
from __future__ import annotations

import argparse
import copy
import json
import urllib.parse
import urllib.request

from packages.library.download import _SafeRedirect
from packages.library.storage import QuotaManager
from scripts.library.acquire_classic_matches import acquire, read_json


def public_json(url: str, referer: str) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": "badmintonTV-library/0.1", "Referer": referer,
    })
    with urllib.request.build_opener(_SafeRedirect()).open(request, timeout=30) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Public metadata exceeds bound")
    result = json.loads(raw)
    if result.get("code") != 0 or not isinstance(result.get("data"), dict):
        raise ValueError("Public metadata unavailable; no alternate access attempted")
    return result["data"]


def resolve(config: dict) -> dict:
    result = copy.deepcopy(config)
    for source in result["sources"]:
        metadata = source["source_metadata"]
        bvid, cid = metadata["bvid"], metadata["cid"]
        page = "https://www.bilibili.com/video/" + bvid + "/"
        if source["source_page_url"] != page:
            raise ValueError("Source page does not match pinned public video")
        view = public_json("https://api.bilibili.com/x/web-interface/view?" +
                           urllib.parse.urlencode({"bvid": bvid}), page)
        rights = view.get("rights", {})
        if (view.get("bvid") != bvid or view.get("cid") != cid or
                view.get("owner", {}).get("mid") != metadata["expected_owner_mid"] or
                view.get("duration") != metadata["expected_duration_seconds"]):
            raise ValueError("Published source identity or duration changed; review required")
        if rights.get("download") != 1 or any(rights.get(k, 0) for k in ("pay", "ugc_pay", "arc_pay")):
            raise ValueError("Public source does not expressly permit free download")
        play = public_json("https://api.bilibili.com/x/player/playurl?" + urllib.parse.urlencode({
            "bvid": bvid, "cid": cid, "qn": 64, "fnval": 0,
        }), page)
        files = play.get("durl", [])
        if len(files) != 1 or play.get("format") not in ("mp4", "mp4720"):
            raise ValueError("Expected one public MP4 file; no alternate client attempted")
        item = files[0]
        if (type(item.get("size")) is not int or not 0 < item["size"] <= source["max_bytes"] or
                abs(item.get("length", 0) / 1000 - view["duration"]) > 2):
            raise ValueError("Public file size or duration violates pinned bounds")
        address = urllib.parse.urlsplit(item["url"])
        if (address.scheme != "https" or address.username or address.password or
                not (address.hostname or "").endswith(".bilivideo.com")):
            raise ValueError("Unexpected public media origin")
        source["resolved_url"] = item["url"]  # memory only; acquire sanitizes receipts
        source["expected_size_bytes"] = item["size"]
        source["source_metadata"] = {
            "title": view["title"],
            "owner": {"mid": view["owner"]["mid"], "name": view["owner"]["name"]},
            "rights": rights, "bvid": bvid, "cid": cid,
            "published_at": view["pubdate"], "quality": play["quality"],
            "size": item["size"], "duration": item["length"] / 1000,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/library/classic_matches.json")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--ffprobe", required=True)
    args = parser.parse_args()
    try:
        config = read_json(args.config)
        result = acquire(resolve(config), quota=QuotaManager(),
                         ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    except Exception as exc:
        # HTTP errors can carry signed URLs; never print their message/traceback.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({key: result[key] for key in (
        "status", "dataset_version", "succeeded", "source_count", "handoff_status"
    )}, ensure_ascii=True))
    return 0 if result.get("status") in ("complete", "ready_for_review") else 1


if __name__ == "__main__":
    raise SystemExit(main())
