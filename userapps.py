"""User-made App Store packages. A zip of HTML/CSS/JS, stored under userapps/."""
import json, os, shutil, time, zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "userapps")
CAT = os.path.join(ROOT, "catalog.json")
os.makedirs(ROOT, exist_ok=True)


def load():
    try:
        with open(CAT) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save(items):
    tmp = CAT + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(items, fh)
    os.replace(tmp, CAT)


def wipe():
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(ROOT, exist_ok=True)


def _safe_name(name):
    name = (name or "index.html").replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def add(blob, name, icon, desc):
    if not blob or len(blob) > 25_000_000:
        raise ValueError("Zip must be under 25 MB.")
    import io
    try:
        z = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        raise ValueError("That file is not a zip.")
    htmls = []
    for info in z.infolist():
        if info.is_dir():
            continue
        rel = _safe_name(info.filename)
        if not rel:
            continue
        if rel.lower().endswith((".html", ".htm")):
            htmls.append(rel)
    if not htmls:
        raise ValueError("The zip needs at least one .html file.")
    entry = "index.html" if "index.html" in htmls else sorted(htmls)[0]
    app_id = "app" + str(int(time.time() * 1000))
    dest = os.path.join(ROOT, app_id)
    os.makedirs(dest, exist_ok=True)
    count = 0
    for info in z.infolist():
        if info.is_dir() or count > 400:
            continue
        rel = _safe_name(info.filename)
        if not rel:
            continue
        target = os.path.realpath(os.path.join(dest, rel))
        if not (target == os.path.realpath(dest) or target.startswith(os.path.realpath(dest) + os.sep)):
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with z.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    item = {
        "id": app_id,
        "name": (name or "My app")[:32],
        "icon": (icon or "📦")[:8],
        "desc": (desc or "Custom app")[:180],
        "entry": entry,
        "size": len(blob),
    }
    items = load()
    items.append(item)
    save(items)
    return item


def remove(app_id):
    app_id = _safe_name(app_id) or ""
    if not app_id or "/" in app_id:
        raise ValueError("Bad app")
    dest = os.path.join(ROOT, app_id)
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
    save([x for x in load() if x.get("id") != app_id])


def resolve(app_id, rel):
    app_id = _safe_name(app_id) or ""
    rel = _safe_name(rel) or ""
    if not app_id or not rel or "/" in app_id:
        return None
    return os.path.realpath(os.path.join(ROOT, app_id, rel)) if False else _inside(app_id, rel)


def _inside(app_id, rel):
    base = os.path.realpath(os.path.join(ROOT, app_id))
    target = os.path.realpath(os.path.join(base, rel))
    if target == base or target.startswith(base + os.sep):
        return target if os.path.isfile(target) else None
    return None
