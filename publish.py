#!/usr/bin/env python3
"""Posting 1 gambar ke Instagram lewat Graph API, dengan pengaman.
Pakai:  python publish.py queue/001-salam-kenal [--dry-run] [--skip-url-check]
Env:    IG_TOKEN (secret), IG_USER_ID, GITHUB_REPOSITORY, GITHUB_SHA/GITHUB_REF_NAME
Token TIDAK PERNAH dicetak. Tanpa --dry-run, meta.json harus "approved": true.
"""
import argparse, json, os, pathlib, struct, sys, time, urllib.error, urllib.parse, urllib.request

HOST = os.environ.get("IG_GRAPH_HOST", "https://graph.facebook.com")
VER = os.environ.get("IG_GRAPH_VERSION", "v23.0")
DISCLAIMER = "Info ini bersifat edukasi umum"
HASHTAG = "#logikatubuh"

def die(msg):
    print("ERROR:", msg); sys.exit(1)

def jpeg_size(path):
    b = pathlib.Path(path).read_bytes()
    if b[:2] != b"\xff\xd8":
        die("image.jpg bukan JPEG (Instagram API hanya menerima JPEG)")
    i = 2
    while i < len(b):
        if b[i] != 0xFF: i += 1; continue
        m = b[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", b[i + 5:i + 9]); return w, h
        i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    die("ukuran JPEG tidak terbaca")

def call(method, path, params):
    token = os.environ.get("IG_TOKEN") or die("IG_TOKEN belum diisi")
    params = dict(params, access_token=token)
    url = f"{HOST}/{VER}/{path}"
    data = None
    if method == "GET":
        url += "?" + urllib.parse.urlencode(params)
    else:
        data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method), timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace").replace(token, "***")
        die(f"Graph API {e.code}: {body}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post_dir")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-url-check", action="store_true")
    a = ap.parse_args()
    d = pathlib.Path(a.post_dir)
    cap = (d / "caption.txt").read_text(encoding="utf-8").strip()
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    reels = meta.get("type") == "REELS"
    img = d / ("cover.jpg" if reels else "image.jpg")
    vid = d / "video.mp4"
    posted = d / "posted.json"

    if posted.exists(): die(f"sudah pernah diposting: {posted.read_text()}")
    if DISCLAIMER not in cap: die("caption wajib memuat disclaimer edukasi umum")
    if HASHTAG not in cap: die("caption wajib memuat #logikatubuh")
    if len(cap) > 2200: die("caption lebih dari 2200 karakter")
    w, h = jpeg_size(img)
    ratio = w / h
    if reels:
        if not vid.exists(): die("video.mp4 tidak ada")
        if vid.stat().st_size > 300_000_000: die("video > 300MB")
        if meta.get("needs_final_audio"): die('meta "needs_final_audio": true — VO final belum dipasang')
        if not (0.5 <= ratio <= 0.6): die(f"cover {w}x{h} bukan 9:16")
    elif not (0.8 <= ratio <= 1.91): die(f"rasio {w}x{h} di luar 4:5 .. 1.91:1")
    print(f"OK  {'reels' if reels else 'gambar'} {w}x{h}, caption {len(cap)} karakter")

    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    ref = os.environ.get("GITHUB_SHA") or os.environ.get("GITHUB_REF_NAME", "main")
    media = "video.mp4" if reels else "image.jpg"
    url = f"https://raw.githubusercontent.com/{repo}/{ref}/{d.as_posix()}/{media}"
    print("URL gambar:", url)
    if not a.skip_url_check:
        try:
            r = urllib.request.urlopen(url, timeout=30)
            ct = r.headers.get("Content-Type", "")
            head = r.read(16)
            ok_type = ("video" in ct or (ct == "application/octet-stream" and head[4:8] == b"ftyp")) if reels else ("image" in ct)
            if r.status != 200 or not ok_type: die(f"URL tidak valid ({r.status}, {ct})")
            print("OK  URL gambar bisa diakses publik")
        except urllib.error.URLError as e:
            die(f"URL gambar tidak bisa diakses: {e} (repo harus publik dan file sudah di-push)")

    if a.dry_run:
        print("DRY RUN selesai. Tidak ada yang diposting."); return
    if not meta.get("approved"): die('meta.json belum "approved": true')

    uid = os.environ.get("IG_USER_ID") or die("IG_USER_ID belum diisi")
    if reels:
        p = {"media_type": "REELS", "video_url": url, "caption": cap, "share_to_feed": "true"}
        cu = f"https://raw.githubusercontent.com/{repo}/{ref}/{d.as_posix()}/cover.jpg"
        p["cover_url"] = cu
    else:
        p = {"image_url": url, "caption": cap}
        if meta.get("alt_text"): p["alt_text"] = meta["alt_text"]
    c = call("POST", f"{uid}/media", p)["id"]
    print("container dibuat:", c)
    for _ in range(60):
        s = call("GET", c, {"fields": "status_code,status"})
        if s.get("status_code") == "FINISHED": break
        if s.get("status_code") in ("ERROR", "EXPIRED"): die(f"container gagal: {s}")
        time.sleep(4)
    else:
        die("container belum FINISHED setelah 4 menit")
    mid = call("POST", f"{uid}/media_publish", {"creation_id": c})["id"]
    info = call("GET", mid, {"fields": "permalink,timestamp"})
    posted.write_text(json.dumps({"media_id": mid, **info}, indent=2))
    print("TERPOSTING:", info.get("permalink"))

if __name__ == "__main__":
    main()
