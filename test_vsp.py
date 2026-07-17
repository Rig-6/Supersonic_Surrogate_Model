from pathlib import Path
import os
import sys


def add_openvsp_paths() -> None:
    openvsp_root = Path(r"C:\OpenVSP\python")

    # Add the parent directory first so utilities can be imported as a top-level module
    if str(openvsp_root) not in sys.path:
        sys.path.insert(0, str(openvsp_root))

    package_roots = [
        openvsp_root / "openvsp",
        openvsp_root / "degen_geom",
        openvsp_root / "utilities",
        openvsp_root / "openvsp_config",
    ]

    for package_root in package_roots:
        if package_root.exists():
            package_root_text = str(package_root)
            if package_root_text not in sys.path:
                sys.path.insert(0, package_root_text)


add_openvsp_paths()

try:
    import openvsp as vsp
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Could not import OpenVSP. Set OPENVSP_PYTHON_PATH to the folder that contains the OpenVSP Python bindings, or install OpenVSP to C:\\OpenVSP\\python."
    ) from exc


# Test Connection

vsp.VSPCheckSetup()
vsp.ClearVSPModel()

# Add parametric pod
pod_id = vsp.AddGeom("POD")
print(f"Successfully connected to OpenVSP on Windows! Added POD with ID: {pod_id}")

