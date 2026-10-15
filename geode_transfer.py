#!/usr/bin/env python3
"""geode-transfer: copy Geode data between iPhones and iPads.

Moves your Geometry Dash saves, Geode mods, mod settings and launcher
preferences from one iOS device to another (or to a folder on your Mac and
back) using `xcrun devicectl`. It needs macOS with Xcode 15 or newer, and a
Geode that was installed with a development profile (Xcode, AltStore,
SideStore), because that is what makes its data folder readable.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

__version__ = "0.1.0"

DATA_ROOT = "Documents/Data/Application"
MANIFEST = "manifest.json"
BACKUP_HOME = Path.home() / "geode-transfer-backups"

CATEGORIES = {
    "saves": "Geometry Dash progress and local levels (CC*.dat)",
    "mods": "Geode mods (the .geode files)",
    "mod-data": "settings and saved data of every mod, key bindings",
    "mod-config": "config folders of mods (can be large)",
    "songs": "downloaded custom songs (Geometry Dash downloads them again if missing)",
    "prefs": "Geode launcher preferences",
}

# Keys the launcher derives from local files (the patched Geometry Dash and its
# tweaks). Copying them to another device would make it skip the patching.
DERIVED_KEYS = (
    "PATCH_CHECKSUM",
    "CURRENT_TWEAK_HASH",
    "GDVerified",
    "GDNeedsUpdate",
    "lastLaunchDataUUID",
    "lastLaunchType",
    "LAUNCH_COUNT",
    "CURRENT_VERSION_TAG",
)
CERT_KEYS = ("LCCertificateData", "LCCertificatePassword", "LCCertificateImported")
# Without the certificate the setup has to run again on the destination.
SETUP_KEYS = ("CompletedSetup", "JITLESS")

# Directories copied as a whole, per category (relative to the data container).
DIR_TASKS = {
    "mods": "Documents/game/geode/mods",
    "mod-data": "Documents/save",
    "mod-config": "Documents/game/geode/config",
}


class TransferError(RuntimeError):
    """An error with a message that is safe to show to the user."""


# ---------------------------------------------------------------- categories

def categorize(rel: str) -> str | None:
    """Return the category of a path relative to the data container, if any."""
    if re.fullmatch(r"Documents/CC[A-Za-z0-9_]*\.dat", rel):
        return "saves"
    if rel.startswith(DIR_TASKS["mods"] + "/"):
        return "mods"
    if rel.startswith(DIR_TASKS["mod-data"] + "/"):
        return "mod-data"
    if rel.startswith(DIR_TASKS["mod-config"] + "/"):
        return "mod-config"
    if re.fullmatch(r"Documents/[^/]+\.(ogg|mp3)", rel):
        return "songs"
    return None


def resolve_categories(only: str | None, skip: str | None) -> list[str]:
    """Turn --only/--skip into an ordered list of category names."""
    def parse(value: str | None) -> list[str]:
        names = [n.strip() for n in (value or "").split(",") if n.strip()]
        unknown = [n for n in names if n not in CATEGORIES]
        if unknown:
            raise TransferError(
                f"unknown categories: {', '.join(unknown)}. "
                f"valid ones: {', '.join(CATEGORIES)}"
            )
        return names

    chosen = parse(only) or list(CATEGORIES)
    skipped = set(parse(skip))
    result = [c for c in CATEGORIES if c in chosen and c not in skipped]
    if not result:
        raise TransferError("nothing to copy: every category was skipped")
    return result


# --------------------------------------------------------------- preferences

def clean_prefs(prefs: dict, include_certificate: bool) -> dict:
    """Return launcher preferences that are safe to apply to another device."""
    cleaned = dict(prefs)
    for key in DERIVED_KEYS:
        cleaned.pop(key, None)
    if not include_certificate:
        for key in CERT_KEYS + SETUP_KEYS:
            cleaned.pop(key, None)
    return cleaned


# ------------------------------------------------------------------ devicectl

HINTS = (
    (("locked",), "the device is locked: unlock it and keep the screen on"),
    (
        ("no devices matched", "unable to find", "not connected", "unavailable", "timed out"),
        "connect the device with a cable, unlock it and tap Trust",
    ),
    (
        ("developer mode",),
        "turn on Developer Mode (Settings > Privacy & Security > Developer Mode)",
    ),
    (
        ("developer disk image", "ddi", "personalized"),
        "open Xcode > Window > Devices and Simulators once so it prepares the device, then retry",
    ),
    (
        ("not debuggable", "get-task-allow"),
        "this app's data can only be read when it was installed with a development "
        "profile (Xcode, AltStore, SideStore); App Store and TrollStore installs are not readable",
    ),
)


def hint_for(text: str) -> str | None:
    lowered = text.lower()
    for needles, hint in HINTS:
        if any(n in lowered for n in needles):
            return hint
    return None


def _clean_output(text: str) -> str:
    skip = ("zoxide", "_ZO_DOCTOR", "If the issue persists", "github.com/ajeetdsouza")
    lines = [ln for ln in text.splitlines() if ln.strip() and not any(s in ln for s in skip)]
    return "\n".join(lines)


def devicectl(args: list[str], *, json_output: bool = False, attempts: int = 1, timeout: int | None = None):
    """Run `xcrun devicectl`. With json_output, return the parsed `result`."""
    last = ""
    for attempt in range(1, attempts + 1):
        with tempfile.TemporaryDirectory(prefix="geode-transfer-json-") as tmp:
            out = Path(tmp) / "out.json"
            cmd = ["xcrun", "devicectl", *args]
            if json_output:
                cmd += ["--json-output", str(out)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc = None
                last = "devicectl timed out"
            if proc is not None and proc.returncode == 0:
                if not json_output:
                    return proc.stdout
                try:
                    return json.loads(out.read_text())["result"]
                except (OSError, ValueError, KeyError) as exc:
                    last = f"could not read devicectl output: {exc}"
            elif proc is not None:
                last = _clean_output(proc.stderr or proc.stdout) or f"devicectl exited with {proc.returncode}"
        if attempt < attempts:
            time.sleep(2 * attempt)
    hint = hint_for(last)
    raise TransferError(last + (f"\nhint: {hint}" if hint else ""))


# -------------------------------------------------------------------- devices

@dataclasses.dataclass
class Device:
    id: str
    udid: str
    name: str
    model: str
    os: str
    kind: str
    transport: str
    pairing: str

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model}, iOS {self.os})"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace(" ", " ")
    return text.casefold().strip()


def parse_devices(result: dict) -> list[Device]:
    devices = []
    for raw in result.get("devices", []):
        hw = raw.get("hardwareProperties", {})
        dev = raw.get("deviceProperties", {})
        conn = raw.get("connectionProperties", {})
        kind = hw.get("deviceType", "")
        if kind not in ("iPhone", "iPad", "iPod"):
            continue
        devices.append(
            Device(
                id=raw.get("identifier", ""),
                udid=hw.get("udid", ""),
                name=dev.get("name", "unnamed"),
                model=hw.get("marketingName", hw.get("productType", kind)),
                os=dev.get("osVersionNumber", "?"),
                kind=kind,
                transport=conn.get("transportType", "?"),
                pairing=conn.get("pairingState", "?"),
            )
        )
    return devices


def list_devices() -> list[Device]:
    return parse_devices(devicectl(["list", "devices"], json_output=True, attempts=2))


def pick_device(devices: list[Device], query: str | None) -> Device:
    if not devices:
        raise TransferError("no iPhone or iPad found. Connect one with a cable, unlock it and tap Trust")
    if query is None:
        if len(devices) == 1:
            return devices[0]
        raise TransferError("more than one device is connected, say which one with --device")
    exact = [d for d in devices if query in (d.id, d.udid)]
    if len(exact) == 1:
        return exact[0]
    wanted = normalize(query)
    matches = [d for d in devices if wanted in normalize(d.name)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        names = ", ".join(d.name for d in devices)
        raise TransferError(f"no device matches '{query}'. Available: {names}")
    raise TransferError(f"'{query}' matches {len(matches)} devices, be more specific: " + ", ".join(d.name for d in matches))


# ------------------------------------------------------------------------ apps

@dataclasses.dataclass
class App:
    bundle_id: str
    name: str
    version: str
    accessible: bool
    url: str


def parse_apps(result: dict) -> list[App]:
    apps = []
    for raw in result.get("apps", []):
        bundle = raw.get("bundleIdentifier", "")
        name = raw.get("name", "")
        if name.casefold() == "geode" or "geode.launcher" in bundle.casefold():
            apps.append(
                App(
                    bundle_id=bundle,
                    name=name,
                    version=raw.get("version", "?"),
                    accessible=bool(raw.get("containerAccessible", False)),
                    url=raw.get("url", ""),
                )
            )
    return apps


def find_app(dev: Device, bundle_id: str | None) -> App:
    result = devicectl(
        ["device", "info", "apps", "--device", dev.id, "--include-all-apps"],
        json_output=True, attempts=2,
    )
    apps = parse_apps(result)
    if bundle_id:
        apps = [a for a in apps if a.bundle_id == bundle_id]
    if not apps:
        raise TransferError(f"Geode is not installed on {dev.name}" + (f" with bundle id {bundle_id}" if bundle_id else ""))
    if len(apps) > 1:
        ids = ", ".join(a.bundle_id for a in apps)
        raise TransferError(f"{dev.name} has several Geode apps, pick one with --bundle-id: {ids}")
    app = apps[0]
    if not app.accessible:
        raise TransferError(
            f"the data of {app.bundle_id} on {dev.name} is not readable.\n"
            "hint: it was not installed with a development profile (Xcode, AltStore, SideStore)"
        )
    return app


def app_is_running(dev: Device, app: App) -> bool:
    if not app.url:
        return False
    try:
        result = devicectl(["device", "info", "processes", "--device", dev.id], json_output=True)
    except TransferError:
        return False
    bundle_dir = app.url.removeprefix("file://").rstrip("/")
    return any(
        str(p.get("executable", "")).removeprefix("file://").startswith(bundle_dir)
        for p in result.get("runningProcesses", [])
    )


# -------------------------------------------------------------------- container

def list_files(dev: Device, bundle_id: str) -> dict[str, int]:
    """Return {path relative to the app container: size}, directories included."""
    result = devicectl(
        ["device", "info", "files", "--device", dev.id,
         "--domain-type", "appDataContainer", "--domain-identifier", bundle_id],
        json_output=True, attempts=3,
    )
    files = {}
    for raw in result.get("files", []):
        path = raw.get("relativePath")
        if path:
            files[path] = int(raw.get("metadata", {}).get("size") or 0)
    return files


def find_containers(files: dict[str, int]) -> list[str]:
    prefix = DATA_ROOT + "/"
    return sorted({p[len(prefix):].split("/")[0] for p in files if p.startswith(prefix) and len(p) > len(prefix)})


def pick_container(files: dict[str, int], wanted: str | None, preferred: str | None = None) -> str:
    containers = find_containers(files)
    if wanted:
        if wanted not in containers:
            raise TransferError(f"no data folder called '{wanted}'. Found: {', '.join(containers) or 'none'}")
        return wanted
    if len(containers) == 1:
        return containers[0]
    if preferred in containers:
        return preferred
    if not containers:
        raise TransferError("Geode has no game data yet. Open it once and let it set up, then retry")
    raise TransferError(f"several data folders found ({', '.join(containers)}), pick one with --container")


@dataclasses.dataclass
class Plan:
    """What would be copied, built from a listing of the container."""
    root: str
    counts: dict[str, int]
    sizes: dict[str, int]
    entries: dict[str, int]  # file path (relative to root) -> size


def build_plan(files: dict[str, int], container: str, categories: list[str]) -> Plan:
    root = f"{DATA_ROOT}/{container}"
    prefix = root + "/"
    parents = {p.rsplit("/", 1)[0] for p in files if "/" in p}
    counts = {c: 0 for c in categories}
    sizes = {c: 0 for c in categories}
    entries = {}
    for path, size in files.items():
        if not path.startswith(prefix) or path in parents:
            continue
        rel = path[len(prefix):]
        cat = categorize(rel)
        if cat in counts:
            counts[cat] += 1
            sizes[cat] += size
            entries[rel] = size
    return Plan(root=root, counts=counts, sizes=sizes, entries=entries)


# ----------------------------------------------------------------------- output

def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def say(message: str = "") -> None:
    print(message, flush=True)


class Progress:
    """A one line status that refreshes every second while work is running."""

    def __init__(self, label: str, status=None) -> None:
        self.label, self.status = label, status
        self.start = time.time()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._tty = sys.stdout.isatty()

    def _line(self) -> str:
        extra = f" {self.status()}" if self.status else ""
        return f"{self.label} {fmt_time(time.time() - self.start)}{extra}"

    def _run(self) -> None:
        step = 0
        while not self._stop.wait(1):
            step += 1
            if self._tty:
                print("\r" + self._line().ljust(78), end="", flush=True)
            elif step % 30 == 0:
                print(self._line(), flush=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()
        if self._tty:
            print("\r" + " " * 78 + "\r", end="")
        say(f"{self.label} done in {fmt_time(time.time() - self.start)}")


def count_local(path: Path) -> int:
    return sum(len(files) for _, _, files in os.walk(path)) if path.exists() else 0


# ------------------------------------------------------------------- copying

COPY = ["device", "copy"]


def pull(dev: Device, bundle_id: str, source: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    devicectl(
        [*COPY, "from", "--device", dev.id, "--domain-type", "appDataContainer",
         "--domain-identifier", bundle_id, "--source", source, "--destination", str(dest)],
        attempts=3,
    )
    if not dest.exists():
        raise TransferError(f"{source} was not copied")


def push(dev: Device, bundle_id: str, source: Path, dest: str) -> None:
    devicectl(
        [*COPY, "to", "--device", dev.id, "--domain-type", "appDataContainer",
         "--domain-identifier", bundle_id, "--source", str(source), "--destination", dest],
        attempts=3,
    )


def run_parallel(jobs: int, tasks: list) -> None:
    """Run callables in a thread pool and raise the first error."""
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for future in [pool.submit(t) for t in tasks]:
            future.result()


# --------------------------------------------------------------------- backup

def describe_plan(plan: Plan, categories: list[str]) -> None:
    say("what will be copied:")
    for cat in categories:
        if cat == "prefs":
            say(f"  {'prefs':<11} launcher preferences")
            continue
        say(f"  {cat:<11} {plan.counts.get(cat, 0):>6} files  {fmt_bytes(plan.sizes.get(cat, 0)):>9}   {CATEGORIES[cat]}")
    total = sum(plan.sizes.values())
    say(f"  {'total':<11} {sum(plan.counts.values()):>6} files  {fmt_bytes(total):>9}")


def do_backup(dev: Device, app: App, out: Path, categories: list[str], *, container: str | None,
              include_certificate: bool, jobs: int, dry_run: bool) -> dict | None:
    say(f"reading {dev.name} ...")
    files = list_files(dev, app.bundle_id)
    name = pick_container(files, container)
    plan = build_plan(files, name, categories)
    say(f"data folder: {name}")
    describe_plan(plan, categories)
    if "prefs" in categories and not include_certificate:
        say("  the certificate and its password are left out (use --include-certificate to copy them)")
    if dry_run:
        return None

    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    data = out / "data"
    tasks = []
    for cat in categories:
        if cat in DIR_TASKS and plan.counts.get(cat):
            rel = DIR_TASKS[cat]
            tasks.append(lambda rel=rel: pull(dev, app.bundle_id, f"{plan.root}/{rel}", data / rel))
    for rel in plan.entries:
        if categorize(rel) in ("saves", "songs") and categorize(rel) in categories:
            tasks.append(lambda rel=rel: pull(dev, app.bundle_id, f"{plan.root}/{rel}", data / rel))

    with Progress("copying from the device", lambda: f"{count_local(data)} files"):
        run_parallel(jobs, tasks)

    prefs_name = None
    if "prefs" in categories:
        raw = out / "prefs" / "raw.plist"
        try:
            pull(dev, app.bundle_id, f"Library/Preferences/{app.bundle_id}.plist", raw)
            prefs = plistlib.loads(raw.read_bytes())
            cleaned = clean_prefs(prefs, include_certificate)
            prefs_name = f"{app.bundle_id}.plist"
            (out / "prefs" / prefs_name).write_bytes(plistlib.dumps(cleaned, fmt=plistlib.FMT_BINARY))
            os.chmod(out / "prefs" / prefs_name, 0o600)
        except TransferError as exc:
            say(f"  could not read the launcher preferences, skipping them ({str(exc).splitlines()[0]})")
        finally:
            raw.unlink(missing_ok=True)

    manifest = {
        "tool": "geode-transfer",
        "version": __version__,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": {"device": dev.name, "model": dev.model, "os": dev.os, "bundleId": app.bundle_id, "container": name},
        "categories": categories,
        "includesCertificate": bool(include_certificate and prefs_name),
        "prefs": prefs_name,
        "files": {rel: size for rel, size in plan.entries.items()},
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1))
    say(f"backup saved in {out}")
    if manifest["includesCertificate"]:
        say("warning: this backup contains your signing certificate and its password. Keep it private and delete it when done.")
    return manifest


# -------------------------------------------------------------------- restore

def read_manifest(folder: Path) -> dict:
    path = folder / MANIFEST
    if not path.exists():
        raise TransferError(f"{folder} is not a geode-transfer backup (no {MANIFEST})")
    manifest = json.loads(path.read_text())
    if manifest.get("tool") != "geode-transfer":
        raise TransferError(f"{folder} was not made by geode-transfer")
    return manifest


def confirm(message: str, target: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    say(message)
    if not sys.stdin.isatty():
        raise TransferError("refusing to overwrite without confirmation. Re-run with --yes")
    answer = input(f"type the name of the device ({target}) to continue: ").strip()
    if normalize(answer) != normalize(target):
        raise TransferError("cancelled")


def do_restore(dev: Device, app: App, folder: Path, categories: list[str], *, container: str | None,
               jobs: int, dry_run: bool, assume_yes: bool, force: bool, safety_backup: bool) -> bool:
    manifest = read_manifest(folder)
    available = [c for c in manifest["categories"] if c in categories]
    if not available:
        raise TransferError("the backup has none of the selected categories")
    say(f"backup of {manifest['source']['device']} from {manifest['createdAt']}")

    say(f"reading {dev.name} ...")
    files = list_files(dev, app.bundle_id)
    preferred = manifest["source"].get("container")
    name = pick_container(files, container, preferred) if find_containers(files) else (container or preferred or "GeometryDash")
    root = f"{DATA_ROOT}/{name}"
    say(f"destination data folder: {name}")

    plan_cats = [c for c in available if c != "prefs"]
    saved = {rel: size for rel, size in manifest["files"].items() if categorize(rel) in plan_cats}
    say("what will be copied:")
    for cat in available:
        if cat == "prefs":
            say(f"  {'prefs':<11} launcher preferences" + ("" if manifest["includesCertificate"] else " (without certificate)"))
            continue
        n = sum(1 for r in saved if categorize(r) == cat)
        s = sum(size for r, size in saved.items() if categorize(r) == cat)
        say(f"  {cat:<11} {n:>6} files  {fmt_bytes(s):>9}   {CATEGORIES[cat]}")
    say("existing files with the same name are overwritten; nothing is deleted")
    if dry_run:
        return True

    if not force and app_is_running(dev, app):
        raise TransferError(f"Geode is open on {dev.name}. Close it completely (swipe it away) and retry, or use --force")
    confirm(f"this will write into Geode's data on {dev.name}.", dev.name, assume_yes)

    if safety_backup and find_containers(files):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = BACKUP_HOME / f"{stamp}-{re.sub(r'[^A-Za-z0-9]+', '-', dev.name).strip('-')}-before-restore"
        say(f"saving your current saves and preferences first in {safe} (private folder, it includes the certificate so you can roll back)")
        do_backup(dev, app, safe, ["saves", "prefs"], container=name, include_certificate=True, jobs=jobs, dry_run=False)

    data = folder / "data"
    tasks = []
    for cat in available:
        if cat in DIR_TASKS and (data / DIR_TASKS[cat]).exists():
            rel = DIR_TASKS[cat]
            tasks.append(lambda rel=rel: push(dev, app.bundle_id, data / rel, f"{root}/{rel}"))
    for rel in saved:
        if categorize(rel) in ("saves", "songs") and (data / rel).exists():
            tasks.append(lambda rel=rel: push(dev, app.bundle_id, data / rel, f"{root}/{rel}"))
    with Progress("copying to the device"):
        run_parallel(jobs, tasks)

    if "prefs" in available and manifest.get("prefs"):
        source = folder / "prefs" / manifest["prefs"]
        if source.exists():
            push(dev, app.bundle_id, source, f"Library/Preferences/{app.bundle_id}.plist")
            say("preferences applied")

    return verify(dev, app, root, saved)


def verify(dev: Device, app: App, root: str, expected: dict[str, int]) -> bool:
    say("checking the copy ...")
    files = list_files(dev, app.bundle_id)
    missing = [r for r in expected if f"{root}/{r}" not in files]
    wrong = [r for r in expected if f"{root}/{r}" in files and files[f"{root}/{r}"] != expected[r]]
    if missing or wrong:
        say(f"problem: {len(missing)} files missing, {len(wrong)} with a different size")
        for rel in (missing + wrong)[:10]:
            say(f"  {rel}")
        return False
    say(f"ok: all {len(expected)} files are on the device with the same size")
    return True


# --------------------------------------------------------------------- commands

def add_selection(p: argparse.ArgumentParser) -> None:
    p.add_argument("--only", help=f"comma list of what to copy: {', '.join(CATEGORIES)}")
    p.add_argument("--skip", help="comma list of categories to leave out, e.g. songs,mod-config")
    p.add_argument("--container", help="name of the data folder inside Geode (found automatically)")
    p.add_argument("--bundle-id", help="Geode's bundle id, if it cannot be detected")
    p.add_argument("--jobs", type=int, default=4, help="parallel copies (default 4)")
    p.add_argument("--dry-run", action="store_true", help="show what would happen without copying")


def cmd_devices(args) -> int:
    devices = list_devices()
    if not devices:
        if args.json:
            say("[]")
            return 1
        say("no iPhone or iPad found. Connect one with a cable, unlock it and tap Trust")
        return 1
    if args.json:
        say(json.dumps([dataclasses.asdict(device) for device in devices]))
        return 0
    rows = [(d.name, d.model, f"iOS {d.os}", d.transport) + ((d.udid,) if args.udid else ()) for d in devices]
    widths = [max(len(v) for v in column) for column in zip(*rows)]
    for row in rows:
        say("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    return 0


def cmd_apps(args) -> int:
    dev = pick_device(list_devices(), args.device)
    apps = parse_apps(devicectl(["device", "info", "apps", "--device", dev.id, "--include-all-apps"],
                                json_output=True, attempts=2))
    if not apps:
        say(f"Geode is not installed on {dev.name}")
        return 1
    for a in apps:
        state = "data readable" if a.accessible else "data NOT readable (needs a development profile)"
        say(f"{a.name} {a.version}  {a.bundle_id}  {state}")
    return 0


def cmd_backup(args) -> int:
    cats = resolve_categories(args.only, args.skip)
    dev = pick_device(list_devices(), args.device)
    app = find_app(dev, args.bundle_id)
    out = Path(args.out).expanduser() if args.out else BACKUP_HOME / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^A-Za-z0-9]+', '-', dev.name).strip('-')}"
    do_backup(dev, app, out, cats, container=args.container, include_certificate=args.include_certificate,
              jobs=args.jobs, dry_run=args.dry_run)
    return 0


def cmd_restore(args) -> int:
    cats = resolve_categories(args.only, args.skip)
    dev = pick_device(list_devices(), args.device)
    app = find_app(dev, args.bundle_id)
    ok = do_restore(dev, app, Path(args.source).expanduser(), cats, container=args.container, jobs=args.jobs,
                    dry_run=args.dry_run, assume_yes=args.yes, force=args.force, safety_backup=not args.no_safety_backup)
    return 0 if ok else 1


def cmd_transfer(args) -> int:
    cats = resolve_categories(args.only, args.skip)
    devices = list_devices()
    src = pick_device(devices, args.source)
    dst = pick_device(devices, args.target)
    if src.id == dst.id:
        raise TransferError("the source and the target are the same device")
    src_app = find_app(src, args.bundle_id)
    dst_app = find_app(dst, args.target_bundle_id or args.bundle_id)
    say(f"{src.label}  ->  {dst.label}")
    work = Path(tempfile.mkdtemp(prefix="geode-transfer-"))
    os.chmod(work, 0o700)
    try:
        folder = work / "backup"
        if args.dry_run:
            do_backup(src, src_app, folder, cats, container=args.container,
                      include_certificate=args.include_certificate, jobs=args.jobs, dry_run=True)
            say("(dry run: nothing was copied)")
            return 0
        if not args.force and app_is_running(dst, dst_app):
            raise TransferError(f"Geode is open on {dst.name}. Close it completely (swipe it away) and retry, or use --force")
        do_backup(src, src_app, folder, cats, container=args.container,
                  include_certificate=args.include_certificate, jobs=args.jobs, dry_run=False)
        ok = do_restore(dst, dst_app, folder, cats, container=args.target_container or args.container, jobs=args.jobs,
                        dry_run=False, assume_yes=args.yes, force=args.force, safety_backup=not args.no_safety_backup)
        if args.keep:
            kept = BACKUP_HOME / f"{dt.datetime.now():%Y%m%d-%H%M%S}-transfer"
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), kept)
            say(f"the intermediate backup was kept in {kept}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geode-transfer", description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", action="version", version=f"geode-transfer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("devices", help="list connected iPhones and iPads")
    p.add_argument("--udid", action="store_true", help="also show each device's UDID")
    p.add_argument("--json", action="store_true", help="print devices as JSON for integrations")
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("apps", help="show the Geode apps on a device and whether their data is readable")
    p.add_argument("--device")
    p.set_defaults(func=cmd_apps)

    p = sub.add_parser("backup", help="save a device's Geode data into a folder on this Mac")
    p.add_argument("--device")
    p.add_argument("--out", help=f"destination folder (default: {BACKUP_HOME}/<date>-<device>)")
    p.add_argument("--include-certificate", action="store_true", help="also save the signing certificate and its password")
    add_selection(p)
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("restore", help="write a backup into a device")
    p.add_argument("source", help="folder made by 'backup'")
    p.add_argument("--device")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--force", action="store_true", help="continue even if Geode seems to be open")
    p.add_argument("--no-safety-backup", action="store_true", help="skip the automatic backup of the device's current saves")
    add_selection(p)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("transfer", help="copy Geode data from one device to another")
    p.add_argument("--from", dest="source", required=True, help="source device (name or id)")
    p.add_argument("--to", dest="target", required=True, help="target device (name or id)")
    p.add_argument("--target-bundle-id", help="Geode's bundle id on the target if it differs")
    p.add_argument("--target-container", help="data folder name on the target if it differs")
    p.add_argument("--include-certificate", action="store_true", help="also copy the signing certificate and its password")
    p.add_argument("--keep", action="store_true", help="keep the intermediate backup on this Mac")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.add_argument("--force", action="store_true", help="continue even if Geode seems to be open")
    p.add_argument("--no-safety-backup", action="store_true", help="skip the automatic backup of the target's current saves")
    add_selection(p)
    p.set_defaults(func=cmd_transfer)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.platform != "darwin" or not shutil.which("xcrun"):
        print("error: geode-transfer needs macOS with Xcode (it uses xcrun devicectl)", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except TransferError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
