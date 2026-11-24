#!/usr/bin/env python3
"""Posting 1 gambar ATAU carousel ke Instagram lewat Graph API, dengan pengaman.
Folder konten:
  - gambar tunggal : image.jpg
  - carousel       : slide-01.jpg, slide-02.jpg, ... (2 sampai 10 file JPEG, ukuran sama)
  meta.json (opsional untuk carousel): "alt_texts": ["alt slide 1", "alt slide 2", ...]
Pakai:  python publish.py queue/001-salam-kenal [--dry-run] [--skip-url-check]
Env:    IG_TOKEN (secret), IG_USER_ID, GITHUB_REPOSITORY, GITHUB_SHA/GITHUB_REF_NAME
Token TIDAK PERNAH dicetak. Tanpa --dry-run, meta.json harus "approved": true.
"""
import argparse, json, os, pathlib, struct, sys, time, urllib.error, urllib.parse, urllib.request

HOST = os.environ.get("IG_GRAPH_HOST", "https://graph.facebook.com")
VER = os.environ.get("IG_GRAPH_VERSION", "v23.0")
DISCLAIMER = "Info ini bersifat edukasi umum"
HASHTAG = "#logikatubuh"  # dicek tanpa membedakan huruf besar/kecil
MAX_SLIDES = 10

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
    slides = sorted(d.glob("slide-*.jpg"))
    single = d / "image.jpg"
    if slides and single.exists():
        die("folder berisi image.jpg DAN slide-*.jpg, pilih salah satu")
    if slides:
        if not (2 <= len(slides) <= MAX_SLIDES):
            die(f"carousel harus 2 sampai {MAX_SLIDES} slide, ditemukan {len(slides)}")
        files = slides
    elif single.exists():
        files = [single]
    else:
        die("tidak ada image.jpg maupun slide-*.jpg di folder")
    carousel = len(files) > 1
    posted = d / "posted.json"

    if posted.exists(): die(f"sudah pernah diposting: {posted.read_text()}")
    if DISCLAIMER not in cap: die("caption wajib memuat disclaimer edukasi umum")
    if HASHTAG not in cap.lower(): die("caption wajib memuat #logikatubuh")
    if len(cap) > 2200: die("caption lebih dari 2200 karakter")
    if cap.count("#") > 30: die("caption lebih dari 30 hashtag")

    sizes = [jpeg_size(f) for f in files]
    for f, (w, h) in zip(files, sizes):
        if not (0.8 <= w / h <= 1.91): die(f"{f.name}: rasio {w}x{h} di luar 4:5 .. 1.91:1")
    if len(set(sizes)) > 1:
        die("semua slide carousel harus berukuran sama: " + ", ".join(f"{f.name}={w}x{h}" for f, (w, h) in zip(files, sizes)))
    w, h = sizes[0]
    kind = f"carousel {len(files)} slide" if carousel else "gambar tunggal"
    print(f"OK  {kind}, {w}x{h}, caption {len(cap)} karakter")

    alts = meta.get("alt_texts") or []
    if alts and len(alts) != len(files):
        die(f"alt_texts berisi {len(alts)} item, jumlah slide {len(files)}")

    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    ref = os.environ.get("GITHUB_SHA") or os.environ.get("GITHUB_REF_NAME", "main")
    urls = [f"https://raw.githubusercontent.com/{repo}/{ref}/{d.as_posix()}/{f.name}" for f in files]
    print("URL pertama:", urls[0])
    if not a.skip_url_check:
        for u in urls:
            try:
                r = urllib.request.urlopen(u, timeout=30)
                ct = r.headers.get("Content-Type", "")
                if r.status != 200 or "image" not in ct: die(f"URL tidak valid ({r.status}, {ct}): {u}")
            except urllib.error.URLError as e:
                die(f"URL gambar tidak bisa diakses: {u} ({e}). Repo harus publik dan file sudah di-push")
        print(f"OK  {len(urls)} URL gambar bisa diakses publik")

    if a.dry_run:
        print("DRY RUN selesai. Tidak ada yang diposting."); return
    if not meta.get("approved"): die('meta.json belum "approved": true')

    uid = os.environ.get("IG_USER_ID") or die("IG_USER_ID belum diisi")

    def wait_finished(cid, what):
        for _ in range(30):
            s = call("GET", cid, {"fields": "status_code,status"})
            if s.get("status_code") == "FINISHED": return
            if s.get("status_code") in ("ERROR", "EXPIRED"): die(f"{what} gagal: {s}")
            time.sleep(4)
        die(f"{what} belum FINISHED setelah 2 menit")

    if carousel:
        kids = []
        for i, u in enumerate(urls):
            p = {"image_url": u, "is_carousel_item": "true"}
            if alts and alts[i]: p["alt_text"] = alts[i]
            kid = call("POST", f"{uid}/media", p)["id"]
            kids.append(kid)
            print(f"slide {i + 1}/{len(urls)} dibuat:", kid)
        for i, kid in enumerate(kids):
            wait_finished(kid, f"slide {i + 1}")
        c = call("POST", f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": cap})["id"]
        print("container carousel dibuat:", c)
        wait_finished(c, "container carousel")
    else:
        p = {"image_url": urls[0], "caption": cap}
        alt = (alts[0] if alts else None) or meta.get("alt_text")
        if alt: p["alt_text"] = alt
        c = call("POST", f"{uid}/media", p)["id"]
        print("container dibuat:", c)
        wait_finished(c, "container")

    mid = call("POST", f"{uid}/media_publish", {"creation_id": c})["id"]
    info = call("GET", mid, {"fields": "permalink,timestamp"})
    posted.write_text(json.dumps({"media_id": mid, **info}, indent=2))
    print("TERPOSTING:", info.get("permalink"))

if __name__ == "__main__":
    main()
