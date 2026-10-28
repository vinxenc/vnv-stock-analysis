"""Read-only: print PyPI metadata (version, dates, deps, wheel sizes) for the libs compared in step 4."""
import json
import urllib.request

PACKAGES = ["numpy", "pandas", "polars", "ta", "pandas-ta", "TA-Lib"]


def wheel_ok(name: str) -> bool:
    return name.endswith(".whl") and ("cp312" in name or "py3-none" in name or "abi3" in name) and (
        "manylinux" in name and "x86_64" in name
        or "macosx" in name and "arm64" in name
        or "py3-none-any" in name
    )


for package in PACKAGES:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{package}/json", timeout=20) as response:
        data = json.load(response)
    info = data["info"]
    files = data["urls"]
    upload = max(file["upload_time_iso_8601"] for file in files) if files else "?"
    print(f"== {package} {info['version']}  uploaded {upload[:10]}  python {info.get('requires_python')}")
    requires = info.get("requires_dist") or []
    print("   requires:", [item for item in requires if "extra ==" not in item][:8])
    for file in files:
        if wheel_ok(file["filename"]):
            print(f"   {file['filename']}  {file['size'] / 1e6:.1f} MB")
    if not any(wheel_ok(file["filename"]) for file in files):
        print("   (no matching wheel; files:", [file["filename"] for file in files][:4], ")")
